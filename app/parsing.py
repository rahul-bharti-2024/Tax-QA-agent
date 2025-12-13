#Done


import os
from dotenv import load_dotenv
from llama_cloud_services import LlamaParse

# 1. Load Environment Variables
load_dotenv()

# Configuration
# You can hardcode this or fetch from .env like os.getenv("DOC_PATH")
SOURCE_PDF_PATH = os.getenv("DOC_PATH", "data/The_Income-tax_Bill_2025.pdf")
OUTPUT_DIR = "parsed_cache"

def parse_and_save():
    # Check API Key
    if not os.getenv("LLAMA_CLOUD_API_KEY"):
        raise ValueError("❌ Missing LLAMA_CLOUD_API_KEY in .env file")

    # Check Input File
    if not os.path.exists(SOURCE_PDF_PATH):
        print(f"❌ Error: Input file not found at: {SOURCE_PDF_PATH}")
        return

    # Create Output Directory if it doesn't exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Generate Output Filename
    # e.g., "data/tax_code.pdf" -> "parsed_cache/tax_code.md"
    base_name = os.path.splitext(os.path.basename(SOURCE_PDF_PATH))[0]
    output_file_path = os.path.join(OUTPUT_DIR, f"{base_name}.md")

    print(f"🚀 Starting LlamaParse for: {SOURCE_PDF_PATH}")
    print("⏳ This may take a while for 500+ pages. Do not close this window...")

    try:
        # Initialize Parser
        # result_type="markdown" is best for preserving headers/structure
        parser = LlamaParse(result_type="markdown", verbose=True)
        
        # Load Data (The actual API call)
        documents = parser.load_data(SOURCE_PDF_PATH)
        
        # Merge all pages into one string
        full_markdown_text = "\n\n".join([doc.text for doc in documents])
        
        # Save to file
        with open(output_file_path, "w", encoding="utf-8") as f:
            f.write(full_markdown_text)
            
        print(f"✅ Success! Parsed data saved to: {output_file_path}")
        print("You can now run your database ingestion script safely.")

    except Exception as e:
        print(f"❌ Fatal Error during parsing: {e}")

if __name__ == "__main__":
    parse_and_save()