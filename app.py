from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Set
from aiohttp import ClientSession
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import asyncio
import certifi
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
import logging
import asyncio
from tenacity import retry, stop_after_attempt, wait_fixed


logging.basicConfig(level=logging.DEBUG)

app = FastAPI()

# Input model for domains
class DomainsRequest(BaseModel):
    domains: List[str]

# Output model for results
class CrawlerResponse(BaseModel):
    results: Dict[str, List[str]]

# Function to extract URLs
def extract_urls(html: str, base_url: str) -> Set[str]:
    """Extract all anchor tag URLs from the HTML."""
    soup = BeautifulSoup(html, 'html.parser')
    links = {urljoin(base_url, link['href']) for link in soup.find_all('a', href=True)}
    print(f"Extracted URLs from {base_url}: {links}")
    return links


@retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
async def fetch_html_with_playwright(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.firefox.launch(
            headless=False,
            args=["--no-remote"]
        )
        page = await browser.new_page()

        # Set extra HTTP headers
        await page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        })

        try:
            # Navigate to the page and wait for it to load
            print(f"Navigating to {url}")
            await page.goto(url, wait_until="networkidle", timeout=120000)
            
            # Add a delay to allow for potential JavaScript loading
            print("Waiting for potential JavaScript execution...")
            await asyncio.sleep(5)

            # Try to get the HTML content using different methods
            html_content = ""
            html_content = await page.content()
            if not html_content.strip():
                html_content = await page.evaluate("document.documentElement.outerHTML")

            print(f"HTML fetched with Playwright for {url}: {html_content[:500]}")

            # Check if the HTML contains any content
            if len(html_content.strip()) > 0:
                return html_content
            else:
                print(f"No content found for {url}")
                return ""

        except Exception as e:
            print(f"Error fetching {url} with Playwright: {e}")
            return ""

    await browser.close()



### fetch html
async def fetch_html(session: ClientSession, url: str) -> str:
    """Fetch HTML content using certifi for SSL."""
    try:
        async with session.get(url, ssl=certifi.where(), timeout=10) as response:
            if response.status == 200:
                return await response.text()
    except Exception as e:
        print(f"Error fetching {url}: {e}")
    return ""


# Function to filter product URLs
def filter_product_urls(urls: Set[str]) -> Set[str]:
    """Filter URLs that match typical product patterns."""
    product_patterns = [
        r'/dp/',                # Amazon
        r'/gp/product/',        # Amazon
        r'/men-',               # Myntra
        r'/women-',             # Myntra
        r'/kids',               # Myntra
        r'/saree',              # Myntra
        r'/product/',           # General
        r'/.*?Categories.*?',   # Myntra with query params
        r'/.*?Brand.*?'         # Myntra with Brand filters
    ]
    filtered_urls = set()
    for url in urls:
        if any(re.search(pattern, url) for pattern in product_patterns):
            filtered_urls.add(url)
    print(f"Filtered Product URLs: {filtered_urls}")
    return filtered_urls


# Asynchronous function to fetch HTML
async def fetch_html(session: ClientSession, url: str) -> str:
    """Fetch the HTML content of a URL asynchronously."""
    try:
        async with session.get(url, ssl=False, timeout=100) as response:
            if response.status == 200:
                html = await response.text()
                print(f"HTML fetched for {url}: {html[:500]}")  # Print first 500 characters for debugging
                return html
            else:
                print(f"Failed to fetch {url}: {response.status}")
    except Exception as e:
        print(f"Error fetching {url}: {e}")
    return ""


# Function to crawl a single domain
async def crawl_domain(session: ClientSession, domain: str) -> List[str]:
    """Crawl a single domain to find product URLs."""
    print(f"Crawling domain: {domain}")
    html = await fetch_html_with_playwright(domain)
    if not html:
        return []
    all_urls = extract_urls(html, domain)
    product_urls = filter_product_urls(all_urls)
    return list(product_urls)

# API endpoint to crawl domains
@app.post("/crawl", response_model=CrawlerResponse)
async def crawl_domains(request: DomainsRequest):
    """API endpoint to crawl multiple domains and return product URLs."""
    results = {}
    async with ClientSession() as session:
        tasks = [crawl_domain(session, domain) for domain in request.domains]
        responses = await asyncio.gather(*tasks)
        for domain, urls in zip(request.domains, responses):
            results[domain] = urls
    return {"results": results}
