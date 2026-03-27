# Inspirations Export Specification

To ensure seamless integration between the **Inspirations AI Generation Pipeline** and the **Next.js Prototype Frontend**, the exported data needs to be highly structured. 

Currently, the frontend relies on a Node.js script (using `cheerio`) to parse Pandoc-generated HTML and extract heavily nested text using regular expressions. This is brittle. To make the frontend consumption robust and "React-friendly," we recommend one of the two approaches below (with **Approach 1** being highly preferred).

---

## APPROACH 1 (Highly Preferred): Direct JSON Export

The absolute easiest and most robust way for a Next.js/React application to consume this data is if the Inspirations pipeline outputs a `.json` file directly alongside any standalone images, bypassing HTML-scraping entirely. 

If the generation pipeline can output JSON, it should follow this exact schema:

```json
{
  "title": "Curated Style Inspiration (Best Of)",
  "categories": [
    {
      "name": "Bathroom",
      "description": "Category description text goes here...",
      "items": [
        {
          "id": "bathroom-1",
          "imageUrl": "/inspirations-images/bathroom-1.jpg",
          "sourceUrl": "https://www.pinterest.com/pin/123456789/",
          "rating": "⭐⭐⭐⭐",
          "description": "This item showcases a transitional bathroom...",
          "tags": ["bathroom", "bathroomdesign", "vanity"]
        }
      ]
    }
  ]
}
```

**Benefits:** 
* Zero parsing required on the frontend.
* Next.js can natively import this object and map over it to render the React components instantly.
* Easily type-checked via TypeScript.

---

## APPROACH 2: Semantic HTML with Data Attributes

If the pipeline *must* generate HTML (e.g., for document portability or viewing outside the app), the HTML should be structured cleanly using semantic elements and **`data-*` attributes** for the metadata. This eliminates the need for regex parsing text nodes.

### Preferred HTML Structure:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Curated Style Inspiration (Best Of)</title>
</head>
<body>
    <h1 class="document-title">Curated Style Inspiration (Best Of)</h1>

    <!-- Wrap each category in a designated section -->
    <section class="curation-category" data-category-name="Bathroom">
        <blockquote class="category-description">
            <p>The predominant aesthetic leans towards a sophisticated blend...</p>
        </blockquote>

        <div class="category-items">
            <!-- Each item is a distinct article with metadata in data attributes -->
            <article class="curation-item" 
                     data-id="bathroom-1"
                     data-rating="⭐⭐⭐⭐"
                     data-source-url="https://www.pinterest.com/pin/123456789/"
                     data-tags="bathroom,bathroomdesign,vanity">
                
                <!-- Ideally images are linked rather than Base64 encoded if possible, 
                     but Base64 is fine if necessary for a single-file portable document -->
                <img class="item-image" src="data:image/jpeg;base64,...(or relative path)..." alt="Bathroom Inspiration">
                
                <p class="item-description">
                    This item showcases a transitional bathroom with a white tub...
                </p>
                
            </article>
            
            <!-- Additional <article> elements... -->
        </div>
    </section>

    <!-- Additional <section> elements... -->
</body>
</html>
```

### Why this HTML structure?
1. **DOM Traversal**: A parser like `cheerio` can easily query `$('.curation-category')` to find categories, and `.find('.curation-item')` to iterate through items.
2. **Metadata Extraction**: Getting the rating is as simple as `$item.attr('data-rating')`. We no longer need to parse `| Rating: ⭐⭐⭐⭐ - Description` with complex regex.
3. **Array Splitting**: Tags can be extracted via `$item.attr('data-tags').split(',')`.

## Summary request for the Codex / Generation Agent:
Please adjust your final formatting phase so that instead of outputting Pandoc-style lists with pipes (`|`) and inline formatting, the output utilizes the **Direct JSON** schema above, or constructs the **Semantic HTML** layout utilizing `data-*` attributes for structured fields.
