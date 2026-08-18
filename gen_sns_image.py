from PIL import Image, ImageDraw, ImageFont
import os
import textwrap

# --- Configuration ---
W, H = 1080, 1350  # SNS post size (vertical, like Instagram/Facebook)
BACKGROUND_COLOR = (30, 30, 60)  # Deep blue-purple
ACCENT_COLOR = (255, 200, 100)  # Warm orange accent
TEXT_COLOR = (255, 255, 255)  # White
GRADIENT_COLOR = (0, 0, 0, 180)  # Semi-transparent black for scrim

# Japanese font paths (WSL with Windows fonts)
FONT_BOLD_PATH = "/mnt/c/Windows/Fonts/YuGothB.ttc"  # Heading
FONT_REG_PATH = "/mnt/c/Windows/Fonts/YuGothR.ttc"  # Body text

# Try to load fonts, fallarial if not available
try:
    FONT_BOLD = ImageFont.truetype(FONT_BOLD_PATH, 48)
    FONT_REG = ImageFont.truetype(FONT_REG_PATH, 36)
    print(f"Fonts loaded: Bold={FONT_BOLD_PATH}, Reg={FONT_REG_PATH}")
except Exception as e:
    print(f"Warning: Could not load Japanese fonts: {e}")
    FONT_BOLD = ImageFont.load_default()
    FONT_REG = ImageFont.load_default()
    FONT_BOLD_PATH = None
    FONT_REG_PATH = None

# --- Create background image ---
def create_background(width, height, color=BACKGROUND_COLOR):
    """Create a solid color background."""
    img = Image.new("RGB", (width, height), color)
    return img

# --- Add gradient scrim (darkened bottom for text readability) ---
def add_gradient_scrim(draw, width, height, top_color=GRADIENT_COLOR, bottom_color=(0, 0, 0, 0), transition_height=300):
    """
    Add a gradient gradient at the bottom of the image for text readability.
    The skill documents dynamically calculating text position based on this.
    """
    # Create a gradient surface
    scrim = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    scrim_draw = ImageDraw.Draw(scrim)
    
    # Draw gradient from bottom up
    for y in range(height):
        ratio = y / height
        # Interpolate alpha: more opaque at bottom, transparent at top
        alpha = int(180 * (ratio ** 0.5))  # Square root for smoother transition
        if alpha > 0:
            scrim_draw.rectangle([0, y, width, y+1], fill=(*top_color[:3], alpha))
    
    # Composite with image
    return scrim

# --- Render text with dynamic positioning ---
def render_text_overlay(draw, text, font, text_color, position, align="left", 
                        wrapper_width=None, line_spacing=6):
    """
    Render text with optional wrapping and dynamic positioning.
    Following the skill's approach of dynamic text block calculation.
    """
    if wrapper_width:
        lines = textwrap.wrap(text, width=int(wrapper_width / 7))  # Approx char width
    else:
        lines = [text]
    
    rendered_lines = []
    for line in lines:
        # Split long lines further if needed
        if font.getlength(line) > (wrapper_width or width):
            sub_lines = textwrap.wrap(line, width=int(wrapper_width / 7) if wrapper_width else 20)
            rendered_lines.extend(sub_lines)
        else:
            rendered_lines.append(line)
    
    # Calculate total text block height
    total_height = sum(font.getlength(line) * 0.2 + line_spacing for line in rendered_lines)  # Approx
    
    # Position based on align
    x, y = position
    if align == "center":
        x -= sum(font.getlength(line) for line in rendered_lines) / 2
    elif align == "right":
        x -= sum(font.getlength(line) for line in rendered_lines)
    
    # Render each line
    for line in rendered_lines:
        draw.text((x, y), line, font=font, fill=text_color)
        y += font.getlength("Ag") + line_spacing  # Approx line height
    
    return rendered_lines

# --- Main generation function ---
def generate_sns_image(
    headline,
    body_text="",
    footer_text="",
    background_color=BACKGROUND_COLOR,
    accent_color=ACCENT_COLOR,
    output_path="sns_image.png"
):
    """
    Generate an SNS hybrid image following the sns-hybrid-image skill methodology.
    - Creates background
    - Adds gradient scrim for text readability
    - Renders headline, body, and footer with dynamic positioning
    - Uses Japanese fonts if available (WSL)
    """
    
    # 1. Create background
    img = create_background(W, H, background_color)
    draw = ImageDraw.Draw(img)
    
    # 2. Add gradient scrim at bottom (skill mentions this for dynamic text positioning)
    scrim = add_gradient_scrim(draw, W, H)
    img = Image.alpha_composite(img.convert("RGBA"), scrim).convert("RGB")
    draw = ImageDraw.Draw(img)
    
    # 3. Render headline (large, bold)
    if headline:
        # Wrap headline to fit width
        wrapper_width = W - 100
        render_text_overlay(
            draw, headline, FONT_BOLD, TEXT_COLOR,
            position=(W // 2, 80),  # Center top
            align="center",
            wrapper_width=wrapper_width,
            line_spacing=10
        )
    
    # 4. Render body text (smaller)
    if body_text:
        wrapper_width = W - 100
        render_text_overlay(
            draw, body_text, FONT_REG, TEXT_COLOR,
            position=(W // 2, 350),  # Below headline
            align="center",
            wrapper_width=wrapper_width,
            line_spacing=8
        )
    
    # 5. Render footer text (smallest, at bottom dynamically)
    # Following the skill: dynamically calculate text block bottom 
    # to avoid overlapping with footer
    if footer_text:
        # Calculate footer position considering previous text
        # The skill dynamically adjusts based on text height
        footer_y = H - 80  # 80px from bottom
        
        # If we have body text above, adjust upward
        # Simple approach: position footer above the body text area
        if body_text:
            footer_y = H - 140  # More space above
        
        # Render footer - smaller font or different style
        try:
            footer_font = ImageFont.truetype(FONT_REG_PATH, 24) if FONT_REG_PATH else ImageFont.load_default()
        except:
            footer_font = ImageFont.load_default()
        
        # Draw footer text
        footer_width = footer_font.getlength(footer_text)
        draw.text(
            ((W - footer_width) / 2, footer_y),
            footer_text,
            font=footer_font,
            fill=(*TEXT_COLOR, 200)  # Slightly transparent
        )
    
    # 6. Add accent/original line (optional decorative element)
    # Simple decorative line at top
    if accent_color:
        for i in range(0, W, 60):
            draw.line([(i, 0), (i + 30, 0)], fill=accent_color, width=3)
    
    # 7. Save image
    img.save(output_path)
    print(f"Image saved to: {output_path}")
    print(f"Image size: {img.size}")
    
    return img

# --- Example usage ---
if __name__ == "__main__":
    print("=" * 60)
    print("SNS ハイブリッド画像生成スキルによるデモ")
    print("=" * 60)
    print()
    print("Japanese font paths:")
    print(f"  Bold: {FONT_BOLD_PATH}")
    print(f"  Reg:  {FONT_REG_PATH}")
    print()
    
    # Generate image with sample text
    generate_sns_image(
        headline="テクノロジーと調和",
        body_text="人工知能と人間が共創する未来へ\n新しい価値を創出する旅へようこそ",
        footer_text="2024 Technology Conference",
        output_path="/home/loser/wsl-projects/sns_demo.png"
    )
    
    print()
    print("※実際の運用ではPollinations.aiで背景写真を取得し、")
    print("  そこ上にテキストオーバーレイを重ねるのが基本ワークフローです。")
    print("  スキル本文にあるcurlコマンドで背景画像を取得できます。")
    print("=" * 60)
