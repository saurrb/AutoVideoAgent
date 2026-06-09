# Page 7 Psychological Facts

This page renders short black-background psychology-fact reels in the reference style tested in `C:\Users\Saurabh\Documents\inner_echoes\page7_test`.

Pipeline:
1. Grok text creates a JSON content card: title, subheading, five points, caption, hashtags.
2. FFmpeg renders the tuned static visual with reference-style audio.
3. Meta UI uploader schedules the reel.
4. Telegram reports success/failure.

Manual render test:

```cmd
python "C:\Users\Saurabh\Documents\AutoVideoAgent\pages\page7_psychological_facts\scripts\render_page7_text_reel.py" --content "C:\Users\Saurabh\Documents\AutoVideoAgent\pages\page7_psychological_facts\content\sample_content.json" --audio "C:\Users\Saurabh\Documents\AutoVideoAgent\pages\page7_psychological_facts\assets\music_reference\reference_audio.wav" --output "C:\Users\Saurabh\Documents\AutoVideoAgent\runs\page7_manual_test.mp4" --duration 9.94
```

Note: the included reference audio was extracted for matching/testing. Replace it with rights-cleared audio before monetized production if needed.
