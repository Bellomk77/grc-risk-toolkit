.PHONY: setup assess test
setup: ; pip install -r requirements.txt
assess: ; python -m grc assess examples/maplewood --out reports/maplewood
test: ; pytest -q
