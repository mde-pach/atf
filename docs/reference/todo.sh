# Every console block carrying `tesh-session` runs against `examples/todo`, the suite this
# documentation describes. tesh runs each session in an empty temporary directory, so this finds
# the checkout through the installed package, which is editable in this repository.
cd "$(python -c 'import atf, pathlib; print(pathlib.Path(atf.__file__).parents[2])')/examples/todo"
rm -f todo.db
python -c "import todo" >/dev/null 2>&1
