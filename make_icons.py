from PIL import Image, ImageDraw
import os

os.makedirs("extension/icons", exist_ok=True)

for size in [16, 32, 48, 128]:
    # Purple background
    img  = Image.new("RGBA", (size, size), (203, 166, 247, 255))
    draw = ImageDraw.Draw(img)

    # Rounded feel — draw a slightly darker purple circle inside
    margin = size // 8
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=(149, 100, 221, 255)
    )

    # White "P" letter centered
    letter_size = size // 2
    x = size // 2 - letter_size // 4
    y = size // 2 - letter_size // 2
    draw.text((x, y), "P", fill=(255, 255, 255, 255))

    img.save(f"extension/icons/icon{size}.png")
    print(f"Success: icon{size}.png created")

print("\nAll icons ready in extension/icons/")