import math
import shutil
import time

DURATION = 2.2
FRAME_INTERVAL = 0.05


def smooth(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * value * (3 - 2 * value)


def portrait_frame(sample, colors, seconds) -> list[str]:
    height = sample["rows"]
    width = sample["columns"]
    t = seconds * (5.2 / DURATION)
    settled = seconds >= DURATION
    travel = -0.35 + 1.85 * smooth((t - 0.5) / 4.4)
    lines = []
    for y, line in enumerate(sample["lines"]):
        row = []
        for x, char in enumerate(line.ljust(width)):
            if char == " ":
                row.append(" ")
                continue
            nx, ny = x / max(1, width - 1), y / max(1, height - 1)
            seed = ((x * 37 + y * 71) % 101) / 101
            visibility = smooth((t - ny * 0.6 - seed * 0.4) / 1.1)
            bits = ord(char) - 0x2800
            mask = sum(
                1 << bit
                for bit in range(8)
                if visibility > ((bit * 13 + math.floor(seed * 100)) % 19) / 20
            )
            glyph = char if settled else chr(0x2800 + (bits & mask))
            distance = (nx * 0.8 + ny * 0.35 - travel) / 0.14
            beam = (
                0
                if settled
                else math.exp(-distance * distance)
                * smooth((t - 0.5) / 0.35)
                * (1 - smooth((t - 4.7) / 0.5))
            )
            shade = 0.84 + 0.16 * math.cos((nx - 0.4) * 2 + ny * 1.5)
            base = [
                math.floor(v * 0.8 + tint * 0.2 + 0.5)
                for v, tint in zip(colors[y][x], (78, 146, 153))
            ]
            opacity = 0.3 + 0.7 * visibility
            rgb = [
                math.floor((v * shade * (1 - beam) + highlight * beam) * opacity + 0.5)
                for v, highlight in zip(base, (193, 143, 127))
            ]
            row.append(f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m{glyph}")
        lines.append("".join(row) + "\033[0m")
    return lines


def play(initial, final, sample, colors, geometry, output) -> bool:
    height = sample["rows"]
    resized = False

    def draw(seconds):
        output.write(f"\033[{height}A\r")
        for line in portrait_frame(sample, colors, seconds):
            output.write("\033[2C" + line + "\033[1B\r")
        output.flush()

    try:
        output.write("\033[?25l" + "\n".join(initial.splitlines()[: height + 1]) + "\n")
        output.flush()
        start = time.monotonic()
        while True:
            if shutil.get_terminal_size() != geometry:
                resized = True
                break
            elapsed = time.monotonic() - start
            draw(min(elapsed, DURATION))
            if elapsed >= DURATION:
                break
            time.sleep(min(FRAME_INTERVAL, DURATION - elapsed))
    except KeyboardInterrupt:
        resized = shutil.get_terminal_size() != geometry
        if not resized:
            draw(DURATION)
    finally:
        output.write("\033[0m\033[?25h")
        output.flush()
    if not resized:
        output.write("\n".join(final.splitlines()[height + 1 :]) + "\n")
        output.flush()
    return resized
