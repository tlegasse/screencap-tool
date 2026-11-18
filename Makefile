.PHONY: test battery check setup

test:
	python3 -m unittest discover -s tests -v

battery:
	python3 tests/battery.py

check:
	bin/clip --check

setup:
	./setup.sh
