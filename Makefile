.PHONY: lldb
lldb:
	lldb -o "settings set target.load-cwd-lldbinit true" -o "command script import ak.py" -p $(PID)

.PHONY: build-dev
build-dev:
	BUILD_PRESET=Debug Meta/ladybird.py run ladybird --debug-process WebContent

.PHONY: profile-valgrind
profile-valgrind:
	valgrind \
		--tool=callgrind \
		--instr-atstart=yes \
		--trace-children=yes \
		--trace-children-skip=/usr/bin/*,/bin/* \
		/home/jarusll/source/ladybird/Build/release/bin/Ladybird

.PHONY: performance
performance:
	perf record
		-o perf.data \
		--call-graph dwarf,8192 \
		--aio -z --sample-cpu \
		Build/release/bin/Ladybird --force-new-process

.PHONY: build
build:
	cmake --preset Debug \
		-S /home/jarusll/source/ladybird \
		-B /home/jarusll/source/ladybird/Build/debug \
		-DLADYBIRD_GUI_FRAMEWORK=Qt \
		-DCMAKE_C_COMPILER=clang \
		-DCMAKE_CXX_COMPILER=clang++ \
		-DCMAKE_C_COMPILER_LAUNCHER=distcc \
		-DCMAKE_CXX_COMPILER_LAUNCHER=distcc
	DISTCC_HOSTS="192.168.0.126/10 localhost/12" ninja -v -C /home/jarusll/source/ladybird/Build/debug -j22
