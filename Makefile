.PHONY: res

RCC4 = pyrcc4
RCC5 = pyrcc5

res: res/quango.qrc
	$(RCC4) -py3 -o quango/res_qt4.py $<
	$(RCC5)      -o quango/res_qt5.py $<

release-patch:
	MODE="patch" $(MAKE) release

release-minor:
	MODE="minor" $(MAKE) release

release:
	ssh jenkinsng.admin.frm2 -p 29417 build -v -s -p GERRIT_PROJECT=$(shell git config --get remote.origin.url | rev | cut -d '/' -f -4 | rev) -p ARCH=all -p MODE=$(MODE) ReleasePipeline

.PHONY: release release-patch release-minor
