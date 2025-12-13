import sys
import os
import time

# Add the directory containing rag_app.py to the Python path
# Assuming rag_app.py is in the 'app' directory next to this script
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

try:
    # Import the core function from your existing application file
    from rag_testing import ask_tax_question
except ImportError:
    print("❌ ERROR: Could not import 'ask_tax_question' from rag_app.py.")
    print("Please ensure your core RAG logic is in a file named 'rag_app.py' inside an 'app' directory.")
    sys.exit(1)

def main_cli_loop():
    """
    Runs the main interactive command-line interface loop.
    """
    print("==============================================================")
    print("🚀 Tax Law RAG CLI (Hybrid Search + Reranker ON)")
    print("==============================================================")
    print("Enter your tax question below. Type 'quit' or 'exit' to end.")
    print("-" * 50)
    
    # Run a quick, simple question once to initialize the models
    print("🔍 Initializing models (one-time setup)...")
    try:
        # We call the function once with a trivial query just to load the LLM/Reranker models into memory.
        # This makes the first user query faster.
        ask_tax_question("What is Section 3?", mode="hybrid", use_reranker=True)
        print("-" * 50)
        print("✅ Models ready. Start asking questions.")
    except Exception as e:
        print(f"❌ Initialization failed: {e}")
        print("Please check your GOOGLE_API_KEY and database connection in your .env file.")
        sys.exit(1)


    while True:
        try:
            # Get user input
            question = input("\n[You] > ").strip()
            
            # Check for exit commands
            if question.lower() in ['quit', 'exit']:
                print("\n👋 Exiting Tax Law RAG CLI. Goodbye!")
                break
            
            if not question:
                continue

            # Call the core RAG function
            # We default to the best-performing mode (Hybrid with Reranker ON)
            start_time = time.time()
            ask_tax_question(question, mode="hybrid", use_reranker=True)
            end_time = time.time()
            
            print(f"\nTime taken for query: {end_time - start_time:.2f} seconds")
            print("-" * 80)

        except Exception as e:
            print(f"\n🚨 An unexpected error occurred: {e}")
            # Continue the loop unless it's a critical system error
            time.sleep(1)

if __name__ == "__main__":
    main_cli_loop()
