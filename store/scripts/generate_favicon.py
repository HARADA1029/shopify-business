# Gemini API でファビコン候補を生成するスクリプト
import os
import base64
from google import genai
from google.genai import types
from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

output_dir = os.path.join(PROJECT_ROOT, "store", "assets", "favicon_candidates")
os.makedirs(output_dir, exist_ok=True)

prompt = (
    "Generate an image of a favicon icon design for a store called HD Toys Store Japan. "
    "The store sells Japanese collectible figures and toys. "
    "Design a simple, bold square icon that works at 32x32 pixels. "
    "Use a dark blue or black background with white or gold accent. "
    "Include the letters HD in a clean modern font, or a simple toy robot silhouette. "
    "The design should look professional and premium. "
    "Output only the icon image on a plain background, no mockups."
)

print("Generating favicon candidates with Gemini Flash...")
print()

# Gemini Flash の画像生成機能を使用
for i in range(4):
    response = client.models.generate_content(
        model="gemini-3.1-flash-image-preview",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["image", "text"],
        ),
    )

    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.mime_type.startswith("image/"):
            path = os.path.join(output_dir, f"favicon_{i+1}.png")
            with open(path, "wb") as f:
                f.write(part.inline_data.data)
            size = os.path.getsize(path)
            print(f"[OK] favicon_{i+1}.png ({size:,} bytes)")
            break
    else:
        print(f"[SKIP] favicon_{i+1}: no image generated")
        if response.text:
            print(f"  Text: {response.text[:100]}")

print()
print(f"Candidates saved in {output_dir}")
