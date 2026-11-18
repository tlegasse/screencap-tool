.PHONY: test check setup

test:
	python3 -m unittest discover -s tests -v

check:
	bin/clip --check

setup:
	./setup.sh
