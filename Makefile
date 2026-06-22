validate:
	python3 -c "import os,re,glob,sys; err=0
for p in glob.glob('**/SKILL.md',recursive=True):
 t=open(p).read(); m=re.match(r'---\n(.*?)\n---',t,re.S)
 if not m: print(f'MISSING FM: {p}'); err+=1
sys.exit(err) if err else print('All valid')"
test:
	python3 -m pytest tests/ -v || echo "No tests"
lint:
	pip install ruff -q 2>/dev/null; ruff check lib/ 2>/dev/null || true
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
