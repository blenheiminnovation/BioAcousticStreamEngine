import argparse
import sys

from ecoacoustics.pipeline import Pipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Real-time ecoacoustic monitoring",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="Path to settings YAML file",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="Print available audio devices and exit",
    )
    args = parser.parse_args()

    if args.list_devices:
        from ecoacoustics.audio.capture import AudioCapture
        AudioCapture.list_devices()
        sys.exit(0)

    pipeline = Pipeline(config_path=args.config)
    pipeline.run()


if __name__ == "__main__":
    main()
