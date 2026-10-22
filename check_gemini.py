import sys
from google import genai

client = genai.Client()  # reads GEMINI_API_KEY from your environment

if len(sys.argv) < 2:
    print("Models your key can use:")
    for m in client.models.list():
        name = m.name.replace("models/", "")
        if "gemini" in name:
            print(" ", name)
    print("\nNow run:  py test_gemini.py MODEL_NAME")
else:
    model = sys.argv[1]
    r = client.models.generate_content(
        model=model, contents="Reply with the single word: ready"
    )
    print(r.text)