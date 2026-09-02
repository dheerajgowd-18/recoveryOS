.PHONY: install test demo benchmark

install:
	pip install -r requirements.txt

test:
	python -m pytest -v

demo:
	python scripts/demo.py

benchmark:
	python scripts/benchmark.py --scenarios 1000 --seeds 42,43,44 --holdout-seeds 45,46
