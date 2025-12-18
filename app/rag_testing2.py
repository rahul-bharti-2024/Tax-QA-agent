import time
import sys
from rag_app import ask_tax_question 


test_questions = [
   
    # "What documents do I need to file my income tax return?",

"How is my taxable income calculated from my gross salary?",

"What deductions can I claim under the Income Tax Act?",

"How do I know if I am a resident of India for tax reasons?",
"Is income from agriculture taxable?",
"What constitutes salary income?",
"How is the value of a self-occupied house determined?",
"How do I check the status of my income tax refund?",
    
]

print("🚀 Starting RAG Stress Test (Low Token Mode)...\n")

for q in test_questions:
    # ask_tax_question(q, mode="hybrid")
    print("\nTEST A: Reranker OFF")
    ask_tax_question(q, mode="hybrid", use_reranker=False)

    print("\nTEST B: Reranker ON")
    ask_tax_question(q, mode="hybrid", use_reranker=True)
    print("\n" + "="*60 + "\n")
    
    sys.stdout.flush() 

    print("Cooling down for 15 seconds to respect rate limits...")
    time.sleep(15)