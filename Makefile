PYTHON ?= python
.PHONY: console-up console-down control-api kind-up k8s-deploy k8s-status
console-up console-down control-api kind-up k8s-deploy k8s-status:
	$(PYTHON) scripts/dev.py $@
.PHONY: setup infra-up infra-down migrate data train-fraud test lint doctor demo api serving-up serving-down traffic
setup:
	$(PYTHON) -m pip install -c requirements.lock -e '.[dev]'
infra-up infra-down migrate data train-fraud test lint doctor demo api serving-up serving-down traffic:
	$(PYTHON) scripts/dev.py $@
