#!/bin/bash
# Terminal fallback: runs the full pipeline (extract -> name -> audio -> sweep)
# with a full log in _logs/. Same engine as the app.
cd "$(dirname "$0")"
mkdir -p _logs
LOG="_logs/run_$(date +%Y-%m-%d_%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
echo "============================================"
echo "  SAMPLE ORGANIZER (CLI)"
echo "  log: $LOG"
echo "============================================"
python3 samplelib.py --root . --phase all
echo ""
echo "Done. Reminder: re-scan the folder in Sononym."
echo "Extracted images in _Docs can be deleted to free space."
read -p "Press Enter to close..."
