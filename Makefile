.PHONY: test check install

test:
	python3 -m unittest discover -s tests -v

check:
	bin/clip --check

install:
	./install.sh
