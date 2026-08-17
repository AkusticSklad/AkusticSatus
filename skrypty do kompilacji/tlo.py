from PIL import Image, ImageDraw, ImageFont

# Wymiary okna instalatora
width, height = 560, 360
img = Image.new("RGBA", (width, height))
draw = ImageDraw.Draw(img)

# Tło: miękki pastelowy gradient (od pudrowego różu do pastelowej lilii)
for y in range(height):
    r = int(255 - (y / height) * 12)
    g = int(225 - (y / height) * 15)
    b = int(238 + (y / height) * 12)
    draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

# Słodka nagłówkowa wstęga / baner
draw.rectangle([(0, 0), (width, 50)], fill=(255, 255, 255, 140))
draw.line([(0, 50), (width, 50)], fill=(240, 180, 205, 255), width=2)

# Próba załadowania eleganckiej czcionki systemowej macOS
try:
    font_title = ImageFont.truetype("/System/Library/Fonts/Supplemental/Avenir Next.ttc", 22)
    font_sub = ImageFont.truetype("/System/Library/Fonts/Supplemental/Avenir Next.ttc", 13)
    font_arrow = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 28)
except Exception:
    font_title = font_sub = font_arrow = ImageFont.load_default()

# Nagłówek i podtytuł
draw.text((width // 2, 18), "🌸  AkusticStatus  🌸", fill=(190, 70, 120), font=font_title, anchor="mm")
draw.text((width // 2, 320), "Przeciągnij aplikację do folderu Applications ✨", fill=(170, 80, 120), font=font_sub, anchor="mm")

# Delikatne pętlowe ramki pod ikony (Aplikacja: X=140, Y=170; Applications: X=420, Y=170)
def draw_card(cx, cy):
    w, h = 110, 110
    x0, y0 = cx - w//2, cy - h//2
    draw.rounded_rectangle([x0, y0, cx + w//2, cy + h//2], radius=18, fill=(255, 255, 255, 180), outline=(245, 170, 200, 255), width=2)

draw_card(140, 170)
draw_card(420, 170)

# Słodka strzałka ze serduszkiem pomiędzy ikonami
draw.text((280, 160), "➔", fill=(225, 100, 150), font=font_arrow, anchor="mm")
draw.text((280, 188), "💖", fill=(225, 100, 150), font=font_sub, anchor="mm")

# Zapisanie pliku tła
img.save("installer_bg.png")
print("Obraz tła 'installer_bg.png' został pomyślnie wygenerowany!")