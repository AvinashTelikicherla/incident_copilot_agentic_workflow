install:
	python -m pip install -r requirements.txt

run:
	python -m src.runner

scenarios:
	python -m src.runner --list-scenarios

eval:
	AUTO_APPROVE=true OFFLINE_LLM=true USE_MOCK_SERVICENOW=true python -m src.evaluation.harness

test:
	pytest -q

mcp:
	python -m src.mcp_server
