"""Write the committed synthetic examples. Not telescope observations."""

from pathlib import Path

from wcsscene.synthetic import write_examples


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    write_examples(root)
    print(f"wrote synthetic examples under {root / 'examples'}")


if __name__ == "__main__":
    main()
