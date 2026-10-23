ifeq ($(shell uname -s),Darwin)
OPEN := open
else
OPEN := xdg-open
endif

render3d: render3d.cpp
	clang++ -std=c++17 -O2 render3d.cpp -o render3d

orbit3d.txt:
	python3 astro.py

run: render3d orbit3d.txt
	./render3d && $(OPEN) render3d.html

clean:
	rm -f render3d render3d.html orbit3d.txt

.PHONY: run clean
