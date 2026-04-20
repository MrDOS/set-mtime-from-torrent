.PHONY: all
all:

.PHONY: check
check:
	isort .
	black .
