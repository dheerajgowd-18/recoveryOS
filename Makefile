.PHONY: install test demo

install:
	pip install -r requirements.txt

test:
	python -m pytest -v

demo:
	python scripts/demo.py
