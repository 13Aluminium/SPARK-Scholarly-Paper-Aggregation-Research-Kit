import re
import sys

import requests
from bs4 import BeautifulSoup
from PyPDF2 import PdfReader
from fpdf import FPDF
import time
import logging


class PDFLinkExtractor:
    def __init__(self, input_pdf_path, output_pdf_path):
        """
        Initialize the PDF Link Extractor with input and output paths
        """
        self.input_pdf_path = input_pdf_path
        self.output_pdf_path = output_pdf_path
        self.metadata = {}

        # Configure logging
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s - %(levelname)s: %(message)s',
                            filename='pdf_link_extraction.log')

    def extract_text_from_pdf(self):
        """
        Extract text from PDF file
        """
        try:
            with open(self.input_pdf_path, 'rb') as file:
                reader = PdfReader(file)
                text = ""
                for page in reader.pages:
                    text += page.extract_text()
            logging.info(f"Successfully extracted text from {self.input_pdf_path}")
            return text
        except Exception as e:
            logging.error(f"Error extracting text from PDF: {e}")
            return ""

    def extract_links_and_dois(self, text):
        """
        Extract links, DOIs, and arXiv references from the text
        """
        # Comprehensive link extraction patterns
        link_patterns = [
            r'https?://[^\s]+',  # Basic HTTP/HTTPS links
            r'www\.[^\s]+',  # Links starting with www
            r'doi\.org/[^\s]+'  # DOI links
        ]

        # DOI pattern
        doi_pattern = r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+'

        # arXiv pattern
        arxiv_pattern = r'arXiv:\d{4}\.\d{4,5}'

        links = []
        dois = []
        arxiv_ids = []

        # Extract links
        for pattern in link_patterns:
            links.extend(re.findall(pattern, text))

        # Extract DOIs
        dois = re.findall(doi_pattern, text)

        # Extract arXiv IDs
        arxiv_ids = re.findall(arxiv_pattern, text)

        # Remove duplicates and clean links
        links = list(set(link.strip(',.()[]') for link in links))
        dois = list(set(dois))
        arxiv_ids = list(set(arxiv_ids))

        logging.info(f"Extracted {len(links)} links, {len(dois)} DOIs, and {len(arxiv_ids)} arXiv IDs")
        return links, dois, arxiv_ids

    def extract_abstract_alternative(self, title):
        """
        Alternative method to extract abstract using multiple APIs
        """
        try:
            # Try Crossref API
            crossref_url = f"https://api.crossref.org/works?query={requests.utils.quote(title)}&rows=1"
            crossref_response = requests.get(crossref_url, timeout=10)

            if crossref_response.status_code == 200:
                data = crossref_response.json()
                works = data.get('message', {}).get('items', [])

                if works:
                    # Try to get abstract from Crossref
                    abstract = works[0].get('abstract')
                    if abstract:
                        return abstract

            # Try Semantic Scholar API
            semantic_url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={requests.utils.quote(title)}&fields=abstract"
            semantic_response = requests.get(semantic_url, timeout=10)

            if semantic_response.status_code == 200:
                data = semantic_response.json()
                papers = data.get('data', [])

                if papers and papers[0].get('abstract'):
                    return papers[0]['abstract']

            return "Abstract not found through APIs"

        except Exception as e:
            logging.error(f"Alternative abstract extraction error: {e}")
            return "Abstract extraction failed"

    def extract_abstract_from_url(self, url):
        """
        Try to extract abstract from webpage
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept-Language': 'en-US,en;q=0.9'
            }

            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code != 200:
                return "Abstract not available"

            soup = BeautifulSoup(response.text, 'html.parser')

            # Try different abstract extraction methods
            abstract_candidates = [
                soup.find('meta', attrs={'name': 'description'}),
                soup.find('div', class_=re.compile('abstract|description', re.IGNORECASE)),
                soup.find('p', class_=re.compile('abstract|description', re.IGNORECASE))
            ]

            for candidate in abstract_candidates:
                if candidate:
                    abstract = candidate.get('content', candidate.text)
                    if abstract and len(abstract) > 50:
                        return abstract.strip()

            return "Abstract not found"

        except Exception as e:
            logging.error(f"URL abstract extraction error for {url}: {e}")
            return "Abstract extraction failed"

    def extract_abstract_from_text(self, text):
        """
        Extract potential abstract from PDF text
        """
        # Regex patterns to find abstract-like text
        abstract_patterns = [
            r'Abstract[:.]?\s*(.+?)(?=\n\n|\n[A-Z]|$)',  # Look for 'Abstract:' or 'Abstract.'
            r'((?:(?!Introduction|References)[\s\S]){50,500})',  # Large text block before Introduction
        ]

        for pattern in abstract_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
            if matches:
                # Take the first match and clean it
                abstract = matches[0]
                if isinstance(abstract, tuple):
                    abstract = abstract[0]

                # Clean up the abstract
                abstract = re.sub(r'\s+', ' ', abstract).strip()

                if len(abstract) > 50:
                    return abstract

        return "No abstract found in text"

    def extract_abstract_from_arxiv(self, url):
        """
        Extract the title and abstract specifically for ArXiv papers
        """
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract title
            title_tag = soup.find('h1', class_='title')
            if title_tag:
                title_text = title_tag.text.replace('Title:', '').strip()
            else:
                title_text = "Title not available"

            # Extract abstract
            abstract_block = soup.find('blockquote', class_='abstract')
            if abstract_block:
                abstract_text = abstract_block.text.replace('Abstract:', '').strip()
            else:
                abstract_text = "Abstract not available"

            return title_text, abstract_text

        except Exception as e:
            logging.error(f"Failed to retrieve metadata from {url}: {e}")
            return "Title retrieval error", "Abstract retrieval error"

    def process_links_and_dois(self, text, links, dois, arxiv_ids):
        for source in list(links) + list(dois) + list(arxiv_ids):
            try:
                time.sleep(0.5)  # Throttle requests

                # For ArXiv references
                if source.startswith('arXiv:'):
                    arxiv_id = source.split(':')[-1]
                    url = f"https://arxiv.org/abs/{arxiv_id}"
                    title, abstract = self.extract_abstract_from_arxiv(url)

                elif "arxiv.org" in source:
                    title, abstract = self.extract_abstract_from_arxiv(source)

                elif source.startswith(('http', 'doi.org', 'www.')):
                    abstract = self.extract_abstract_from_url(source)
                    title = self.extract_title_from_url(source)

                if not abstract:
                    title = self.extract_title_from_url(source)
                    abstract = self.extract_abstract_alternative(title)

                if not abstract:
                    abstract = self.extract_abstract_from_text(text)

                self.metadata[source] = {
                    'title': title,
                    'abstract': abstract
                }

            except Exception as e:
                logging.error(f"Failed processing source {source}: {e}")
                self.metadata[source] = {
                    'abstract': 'Failed to get Abstract',
                    'title': 'Unknown Title'
                }

    def create_output_pdf(self):
        """
        Generate output PDF with extracted metadata and abstracts
        """
        try:
            if not self.metadata:
                logging.warning("No metadata found. PDF generation skipped.")
                print("No links or abstracts found to generate PDF.")
                return

            pdf = FPDF()
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.add_page()

            # Use a Unicode font
            pdf.add_font("DejaVu", '', "DejaVuSans.ttf", uni=True)
            pdf.set_font("DejaVu", size=12)

            pdf.cell(0, 10, txt="Extracted Links, Titles, and Abstracts", ln=True, align='C')
            pdf.ln(10)

            for idx, (source, info) in enumerate(self.metadata.items(), start=1):
                truncated_source = source[:100] + '...' if len(source) > 100 else source
                pdf.cell(0, 10, txt=f"{idx}. Source: {truncated_source}", ln=True)

                abstract = info.get('abstract', 'No abstract available')
                pdf.multi_cell(0, 10, txt=f"Abstract: {abstract[:500]}...", align='L')
                pdf.ln(5)

            pdf.output(self.output_pdf_path)
            logging.info(f"Output PDF created at {self.output_pdf_path}")
            print(f"PDF successfully generated at {self.output_pdf_path}")

        except PermissionError:
            logging.error(f"Permission denied when writing to {self.output_pdf_path}")
            print(f"Error: Cannot write to {self.output_pdf_path}. Check file permissions.")
        except IOError as e:
            logging.error(f"IO error when writing PDF: {e}")
            print(f"IO Error: {e}")
        except Exception as e:
            logging.error(f"Unexpected error in PDF creation: {e}")
            print(f"Unexpected error: {e}")

    def create_output_html(self, html_output_path):
        """
        Generate an HTML file with extracted metadata, including paper name, abstract, and link
        """
        try:
            if not self.metadata:
                logging.warning("No metadata found. HTML generation skipped.")
                print("No metadata found to generate HTML.")
                return

            # Start HTML content
            html_content = """
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Extracted Research Papers</title>
                <style>
                    body { font-family: Arial, sans-serif; margin: 20px; }
                    table { width: 100%; border-collapse: collapse; margin-top: 20px; }
                    th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                    th { background-color: #f4f4f4; }
                    tr:nth-child(even) { background-color: #f9f9f9; }
                    tr:hover { background-color: #f1f1f1; }
                    a { color: #007BFF; text-decoration: none; }
                    a:hover { text-decoration: underline; }
                </style>
            </head>
            <body>
                <h1>Extracted Research Papers</h1>
                <table>
                    <thead>
                        <tr>
                            <th>Index</th>
                            <th>Name of the Paper</th>
                            <th>Abstract</th>
                            <th>Link</th>
                        </tr>
                    </thead>
                    <tbody>
            """

            # Add rows for each paper
            for idx, (source, info) in enumerate(self.metadata.items(), start=1):
                name = self.extract_title_from_url(source)
                abstract = info.get('abstract', 'No abstract available')
                link = f"<a href='{source}' target='_blank'>{source}</a>"
                html_content += f"""
                    <tr>
                        <td>{idx}</td>
                        <td>{name}</td>
                        <td>{abstract[:500]}...</td>
                        <td>{link}</td>
                    </tr>
                """

            # End HTML content
            html_content += """
                    </tbody>
                </table>
            </body>
            </html>
            """

            # Write HTML to file
            with open(html_output_path, 'w', encoding='utf-8') as html_file:
                html_file.write(html_content)

            logging.info(f"Output HTML created at {html_output_path}")
            print(f"HTML successfully generated at {html_output_path}")

        except Exception as e:
            logging.error(f"Unexpected error in HTML creation: {e}")
            print(f"Unexpected error: {e}")

    def extract_title_from_url(self, url):
        """
        Extract a title from the URL or webpage if metadata is present.
        """
        try:
            # Handle ArXiv URLs
            if 'arxiv.org' in url:
                arxiv_id = url.split('/')[-1]
                title, _ = self.extract_abstract_from_arxiv(url)  # Fetch title directly from arXiv page
                return title if title != "Title not available" else f"ArXiv Paper ID: {arxiv_id}"

            # Handle DOI URLs
            elif 'doi.org' in url:
                title = self.extract_abstract_alternative(url)  # Use DOI to fetch title via alternative method
                return title if title != "Abstract extraction failed" else f"DOI Reference: {url.split('/')[-1]}"

            # For general sources, try to fetch the title from the webpage
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept-Language': 'en-US,en;q=0.9'
            }

            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                title_tag = soup.find('title')
                if title_tag and title_tag.text.strip():
                    return title_tag.text.strip()

            # Fallback to last part of the URL if no title found
            return url.split('/')[-1]

        except Exception as e:
            logging.error(f"Error extracting title from URL {url}: {e}")
            return "Unknown Title"

    def workflow(self):
        """
        Main workflow method
        """
        try:
            # Extract text from PDF
            text = self.extract_text_from_pdf()

            # Extract links, DOIs, and arXiv IDs
            links, dois, arxiv_ids = self.extract_links_and_dois(text)

            # Process links, DOIs, and arXiv IDs
            self.process_links_and_dois(text, links, dois, arxiv_ids)

            # Create output PDF
            self.create_output_pdf()

            # Create output HTML
            html_output_path = self.output_pdf_path.replace(".pdf", ".html")
            self.create_output_html(html_output_path)

            print(f"Extraction complete. Outputs saved to PDF: {self.output_pdf_path} and HTML: {html_output_path}")

        except Exception as e:
            logging.error(f"Workflow error: {e}")


def loading_bar(total, current):
    """
    Displays a loading bar in the terminal.

    Args:
        total (int): Total number of steps for the progress.
        current (int): Current step being completed.
    """
    progress = current / total
    bar_length = 50  # Length of the progress bar
    block = int(round(bar_length * progress))
    bar = f"[{'#' * block}{'-' * (bar_length - block)}] {progress * 100:.2f}%"
    sys.stdout.write(f"\r{bar}")
    sys.stdout.flush()

# Main execution
if __name__ == "__main__":
    input_pdf_path = input("write the name of research paper you want")  # Replace with your PDF path
    output_pdf_path = "extracted_links_and_abstracts.pdf"

    total_steps = 100
    for i in range(total_steps + 1):
        loading_bar(total_steps, i)
        time.sleep(0.1)
    extractor = PDFLinkExtractor(input_pdf_path, output_pdf_path)
    extractor.workflow()  # Changed from run() to workflow()
    # Simulate work being done
