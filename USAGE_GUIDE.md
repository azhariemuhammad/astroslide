# AstroSlide Usage Guide

## Getting Started

### 1. Access the Application

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

### 2. Upload Your Image

1. Drag and drop your astrophotography image onto the upload zone, or click to browse
2. Supported formats: **JPEG, PNG, TIFF, FITS**
3. Maximum file size: **50MB**

### 3. Choose Your Enhancement Preset

After uploading, you'll see four preset options:

#### 🌙 Mineral Moon
**Best for:** Moon surface images

Creates the dramatic "mineral moon" effect by amplifying the subtle colors that reveal lunar geology:
- **Blue/Purple**: Titanium-rich maria (seas)
- **Orange/Brown**: Iron-rich regions
- **Yellow**: Intermediate mineral compositions

**When to use:**
- Full moon or near-full moon images
- High-resolution lunar surface photos
- Images from telescopes or smart telescopes

**When NOT to use:**
- Crescent moon phases
- Planets or deep sky objects
- Very noisy images

#### 🌌 Deep Sky Boost
**Best for:** Nebulae, galaxies, and star clusters

Optimized for deep space objects with:
- Enhanced faint details through histogram stretching
- Moderate saturation boost for nebula colors
- Star sharpening with unsharp mask
- Noise reduction for long exposures

**When to use:**
- Emission nebulae (Orion, Lagoon, etc.)
- Reflection nebulae
- Galaxies (Andromeda, Whirlpool, etc.)
- Star clusters

#### 🪐 Planet Sharp
**Best for:** Planets and detailed lunar features

Maximizes detail for planetary imaging:
- Strong sharpening for surface details
- Mild histogram stretch to preserve atmosphere
- Aggressive noise reduction
- Minimal saturation changes

**When to use:**
- Jupiter, Saturn, Mars, Venus
- Detailed lunar crater imaging
- Solar imaging (with proper filters!)
- High-magnification planetary work

#### ✨ General Auto
**Best for:** General astrophotography

Balanced enhancement suitable for any astrophoto:
- Moderate histogram stretch
- Gentle saturation boost (15%)
- Light noise reduction
- Safe default for unknown subjects

**When to use:**
- Mixed field images (stars + nebula)
- Wide-field astrophotography
- When you're unsure which preset to use
- As a starting point before trying other presets

### 4. Enhance Your Image

1. Select your desired preset by clicking on it
2. Click the **"Enhance with [Preset Name]"** button
3. Wait for processing (typically 5-15 seconds)
4. The enhanced image will appear in a before/after slider

### 5. Compare Results

- **Drag the slider** left and right to compare original vs. enhanced
- The slider is touch-friendly on mobile devices
- Original is on the left, enhanced is on the right

### 6. Download Your Image

1. Click **"Download Enhanced"** to save your processed image
2. The file will be saved as `[original_name]_enhanced.jpg`
3. Images are saved at full resolution with high quality (98% JPEG quality)

### 7. Try Another Image or Preset

- Click **"Upload New Image"** to process a different image
- You can upload the same image again and try a different preset

## Tips for Best Results

### Image Quality Matters

**Good Input = Great Output**
- Use the highest resolution available
- Ensure proper focus during capture
- Stack multiple frames when possible
- Avoid over-exposed images

### Stacking Before Enhancement

For best results, stack your images first using:
- **Seestar/Dwarf App**: Use built-in stacking
- **DeepSkyStacker** (free, Windows/Mac)
- **Siril** (free, cross-platform)
- **PixInsight** (paid, professional)

Then upload the stacked result to AstroSlide for enhancement.

### Choosing the Right Preset

| Subject | Recommended Preset | Alternative |
|---------|-------------------|-------------|
| Full Moon | Mineral Moon | Planet Sharp |
| Crescent Moon | Planet Sharp | General Auto |
| Jupiter/Saturn | Planet Sharp | General Auto |
| Orion Nebula | Deep Sky Boost | General Auto |
| Andromeda Galaxy | Deep Sky Boost | General Auto |
| Milky Way | General Auto | Deep Sky Boost |
| Star Trails | General Auto | - |

### Processing Workflow

**Recommended workflow:**
1. Capture multiple frames
2. Stack frames (using telescope app or stacking software)
3. Upload stacked image to AstroSlide
4. Try different presets to see which looks best
5. Download your favorite result
6. Optional: Further processing in other tools

### Mobile Usage

AstroSlide is fully mobile-responsive:
- Upload directly from your phone's gallery
- Swipe the comparison slider with your finger
- Perfect for processing images from smart telescope apps
- Share directly from your mobile device

## Advanced Usage

### API Access

You can also use AstroSlide programmatically:

#### Get Available Presets
```bash
curl http://localhost:8000/api/presets
```

#### Enhance an Image
```bash
curl -X POST http://localhost:8000/api/enhance \
  -F "file=@moon.jpg" \
  -F "preset=mineral_moon" \
  -o response.json
```

The response includes the enhanced image as a base64-encoded data URL.

### FITS File Support

AstroSlide supports FITS files (Flexible Image Transport System):
- Common in professional astronomy
- Preserves full bit depth and metadata
- Automatically normalized to 0-255 range for processing
- Grayscale FITS files are converted to RGB

### Batch Processing

For batch processing multiple images:
1. Use the API endpoints programmatically
2. Create a simple script to loop through files
3. Each request processes one image with your chosen preset

## Troubleshooting

### Upload Fails

**Problem:** File won't upload or shows error

**Solutions:**
- Check file size (max 50MB)
- Verify file format (JPEG, PNG, TIFF, FITS)
- Try a different browser
- Check internet connection

### Processing Takes Too Long

**Problem:** Image processing exceeds 30 seconds

**Solutions:**
- Reduce image size before uploading
- Check server load (backend logs)
- Ensure adequate system resources
- Try a smaller test image first

### Colors Look Wrong

**Problem:** Enhanced image has unnatural colors

**Solutions:**
- Try a different preset
- Ensure you're using the right preset for your subject
- Check that original image isn't corrupted
- Mineral Moon is intentionally dramatic - try General Auto for subtle enhancement

### Slider Not Working

**Problem:** Before/after slider doesn't respond

**Solutions:**
- Refresh the page
- Try a different browser
- Check browser console for errors
- Ensure JavaScript is enabled

### Download Fails

**Problem:** Can't download enhanced image

**Solutions:**
- Check browser download permissions
- Try right-click > "Save Image As"
- Ensure popup blocker isn't interfering
- Check available disk space

## Performance Notes

### Processing Times

Typical processing times by image size:
- **Small (< 2MB)**: 3-5 seconds
- **Medium (2-10MB)**: 5-15 seconds
- **Large (10-50MB)**: 15-30 seconds

Processing time also depends on:
- Server CPU performance
- Concurrent users
- Image complexity
- Selected preset (Mineral Moon is slightly slower)

### Resource Usage

**Backend Requirements:**
- Python 3.10+
- 2GB+ RAM recommended
- CPU: Multi-core recommended for faster processing

**Frontend Requirements:**
- Modern web browser (Chrome, Firefox, Safari, Edge)
- JavaScript enabled
- 100MB+ free RAM

## Privacy & Security

- **No data storage**: Images are processed in memory only
- **No user accounts**: No registration required
- **Temporary processing**: Images are not saved on the server
- **Local deployment**: Can run entirely on your own machine
- **Open source**: Full transparency of code and algorithms

## Getting Help

### Resources

- **Documentation**: See README.md and QUICKSTART.md
- **Mineral Moon Guide**: See MINERAL_MOON.md
- **API Documentation**: http://localhost:8000/docs
- **Technical Details**: See technical-steps.md

### Common Questions

**Q: Can I process the same image multiple times?**
A: Yes! Upload the same image and try different presets.

**Q: Will this work with smartphone photos of the night sky?**
A: Yes, but results depend on image quality. Works best with telescope images.

**Q: Is the Mineral Moon effect scientifically accurate?**
A: The colors are real but dramatically exaggerated. Use Planet Sharp for accuracy.

**Q: Can I undo the enhancement?**
A: The original image is preserved. Download both if needed.

**Q: Does this work offline?**
A: Yes, if you run it locally with the local development setup.

---

**Happy astrophotography! ✨🔭🌙**

