"""
Makes the game's short alert sounds (game/sounds/*.ogg): check, game-start, game-end, low-time and notify.

The sounds are synthesized (soft bell-like tones with a quick fade in and a long fade out, so they don't click)
and written as OGG Vorbis, which works in the browser too. Their loudness is set to sit next to move-sound.ogg.

Needs numpy and soundfile (pip install numpy soundfile); the game itself doesn't, it only plays the .ogg files.

    python tools/make_sounds.py            # writes the files into game/sounds/
"""
import os
import sys

import numpy as np
import soundfile as sf

RATE = 48000  # like the other sounds
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'game', 'sounds')
# overall loudness: move-sound.ogg peaks near 0.46 but is a short knock; a ringing tone sounds louder at the
# same peak, so the tones peak lower
PEAK = {'check': 0.3, 'game-start': 0.30, 'game-end': 0.30, 'low-time': 0.30, 'notify': 0.30}


def silence(seconds):
    return np.zeros(int(RATE * seconds))


def tone(freq, seconds, decay=6.0, partials=((1, 1.0), (2, 0.25), (3, 0.08)), attack=0.006):
    """A bell-like note: a few harmonics, each fading out (higher ones faster), with a short fade in."""
    t = np.arange(int(RATE * seconds)) / RATE
    wave = np.zeros_like(t)
    for multiple, level in partials:
        wave += level * np.sin(2 * np.pi * freq * multiple * t) * np.exp(-decay * multiple ** 0.5 * t)
    fadeIn = np.minimum(1.0, t / attack)
    fadeOut = np.minimum(1.0, (seconds - t) / 0.03)  # the last 30 ms go to zero: no click at the end
    return wave * fadeIn * fadeOut


def mix(length, *parts):
    """Adds (start seconds, samples) parts into one buffer of length seconds."""
    out = silence(length)
    for start, samples in parts:
        i = int(RATE * start)
        n = min(len(samples), len(out) - i)
        out[i:i + n] += samples[:n]
    return out


def check():  # two short bright blips
    blip = tone(1568, 0.09, decay=28, partials=((1, 1.0), (2, 0.35), (3, 0.12)))  # G6
    return mix(0.24, (0.0, blip), (0.12, blip))


def gameStart():  # a soft rising two-note: C5, then G5
    return mix(0.62, (0.0, tone(523.25, 0.3, decay=7)), (0.16, tone(783.99, 0.46, decay=6)))


def gameEnd():  # a calm falling three-note chime: G5, E5, C5
    return mix(0.68, (0.0, tone(783.99, 0.3, decay=7)), (0.15, tone(659.25, 0.3, decay=7)),
               (0.3, tone(523.25, 0.38, decay=5)))


def lowTime():  # a short soft tick
    rng = np.random.default_rng(7)
    t = np.arange(int(RATE * 0.06)) / RATE
    noise = np.convolve(rng.standard_normal(len(t)), np.ones(6) / 6, mode='same')  # softened noise
    click = (0.5 * noise + np.sin(2 * np.pi * 2200 * t)) * np.exp(-90 * t) * np.minimum(1.0, t / 0.002)
    return mix(0.08, (0.0, click * np.minimum(1.0, (0.06 - t) / 0.01)))  # fades to zero at the end


def notify():  # a gentle two-tone: A5, then E5 (like a soft doorbell)
    return mix(0.6, (0.0, tone(880.0, 0.32, decay=8)), (0.17, tone(659.25, 0.43, decay=6)))


SOUNDS = {'check': check, 'game-start': gameStart, 'game-end': gameEnd, 'low-time': lowTime, 'notify': notify}


def loudness(samples):
    """(peak, RMS over the audible part) of a sound, for comparing with the others."""
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    audible = samples[np.abs(samples) > 0.01]
    return float(np.abs(samples).max()), float(np.sqrt((audible ** 2).mean())) if len(audible) else 0.0


def main():
    os.makedirs(OUT, exist_ok=True)
    reference = os.path.join(OUT, 'move-sound.ogg')
    if os.path.exists(reference):
        print("%-16s peak %.2f  rms %.3f" % (('move-sound',) + loudness(sf.read(reference)[0])))
    for name, make in SOUNDS.items():
        samples = make()
        samples = samples / np.abs(samples).max() * PEAK[name]
        stereo = np.column_stack([samples, samples])  # stereo, like the other sounds
        path = os.path.join(OUT, name + '.ogg')
        sf.write(path, stereo, RATE, format='OGG', subtype='VORBIS')
        peak, rms = loudness(sf.read(path)[0])
        print("%-16s peak %.2f  rms %.3f  %.2f s  %d bytes" % (name, peak, rms, len(samples) / RATE,
                                                                os.path.getsize(path)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
