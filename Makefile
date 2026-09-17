CXX ?= g++
CXXFLAGS ?= -std=c++11 -O3 -DNDEBUG -Wall -Wextra -Wpedantic
PYTHON ?= python3

.PHONY: all solver test sanitize clean
all: solver
solver: .build/native_lns

.build/native_lns: solvers/native_lns.cpp
	mkdir -p .build
	$(CXX) $(CXXFLAGS) $< -o $@

test: solver
	NATIVE_TEST_BINARY=$(CURDIR)/.build/native_lns $(PYTHON) -m unittest discover -s tests -v

sanitize:
	mkdir -p .build
	$(CXX) -std=c++11 -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer solvers/native_lns.cpp -o .build/native_sanitized
	NATIVE_TEST_BINARY=$(CURDIR)/.build/native_sanitized $(PYTHON) -m unittest discover -s tests -v

clean:
	rm -rf .build
