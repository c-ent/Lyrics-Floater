# Lyrics Floater

A small Python project that displays timed lyric animations using `tkinter`.

Each script contains a `LYRICS` list with timed events and display styles.

## Requirements

- Python 3
- `tkinter` (usually included with standard Python installs)

## Run

From the project folder, run one of the scripts:

```bash
python kiss_me.py
python nowhere_nobody.py
python stupid_song.py
```

## Lyrics format

The scripts support multiple lyric event types, including:

- `Normal line`
- `Word-timed`
- `Side-by-side`
- `Shout collage`
- `Linger`
- `Slam`
- `Tinker swarm`

Each file includes instructions at the top describing the exact `LYRICS` format.

## Customize

To change the song display, edit the `LYRICS` list inside each script.

- `timestamp`: time in seconds from the song start
- `hold`: how long the line stays after typing finishes (`None` means forever)
- `type_speed`: delay between characters, in seconds
- `w`: text window width

## Notes

The project uses `tkinter` windows and animation effects to create dynamic lyric visuals. If a script fails due to missing `tkinter`, install Python with the Tk support or use a distribution that includes it.
