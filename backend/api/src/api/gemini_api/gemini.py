from google import genai

client = genai.Client()

response = client.models.generate_content(
    model="gemini-3-flash-preview",
    contents="Hello gemini! Explain what you are in a short paragraph.",
)

print(response.text)
