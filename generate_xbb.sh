#!/bin/bash
# Generate .xbb bounding box files for all images

echo "Generating .xbb files for JPG/PNG images..."

count=0
# Find all jpg, jpeg, and png files and generate .xbb files for them
find Figures Pictures -type f \( -name '*.jpg' -o -name '*.jpeg' -o -name '*.png' \) | while read file; do
    ebb -x "$file" 2>&1 | grep -v "Inconsistent resolution"
    ((count++))
    if [ $((count % 100)) -eq 0 ]; then
        echo "Processed $count files..."
    fi
done

# Count generated files
xbb_count=$(find Figures Pictures -name '*.xbb' | wc -l)
echo ""
echo "Generated $xbb_count .xbb files"

