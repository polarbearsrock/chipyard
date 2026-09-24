# s2chitni & Claude (AI-generated)
#
# The offline sbt environment for recipes that may re-assemble chipyard.jar
# (any 'make -C sims/<simulator>' whose jar is out of date): the RTA V4 recipe
# (rta_v4/Makefile) and DORA's (dora/Makefile, Chisel pilot step 5). Include it
# after setting CHIPYARD_ROOT, and make every target that runs such a make
# depend on offline-sbt-check.
#
# Chipyard's variables.mk does 'export SBT_OPTS ?= ...', so the SBT_OPTS
# exported here replaces Chipyard's and must be complete: Chipyard's own ivy
# home, global base and boot directory under $(CHIPYARD_ROOT); sbt's user.home
# below $(TMPDIR), because sbt writes .cache/JNA and .config/jgit there, which
# would otherwise land in $HOME; and, unless DORA_SBT_ONLINE=1, a dead proxy,
# so nothing is fetched. COURSIER_CACHE points sbt's dependency resolution at
# DORA_COURSIER_CACHE, the pinned cache DORA's scripts/dora-chisel-build
# resolves from too; without it sbt would resolve through ~/.cache/coursier.
#
# Variables (defaults in brackets):
#   DORA_COURSIER_CACHE  the Coursier cache [$(TMPDIR)/tars/cache/chipyard/coursier]
#   CHIPYARD_SBT_HOME    sbt's user.home [$(TMPDIR)/chipyard-sbt-home]
#   DORA_SBT_ONLINE=1    allow network access (the cache stays DORA_COURSIER_CACHE)

ifndef CHIPYARD_ROOT
$(error include offline-sbt.mk after setting CHIPYARD_ROOT)
endif
ifndef TMPDIR
$(error TMPDIR must be set)
endif

DORA_COURSIER_CACHE ?= $(TMPDIR)/tars/cache/chipyard/coursier
CHIPYARD_SBT_HOME ?= $(TMPDIR)/chipyard-sbt-home

OFFLINE_SBT_PROXY := -Dhttp.proxyHost=127.0.0.1 -Dhttp.proxyPort=9 \
  -Dhttps.proxyHost=127.0.0.1 -Dhttps.proxyPort=9

export COURSIER_CACHE := $(DORA_COURSIER_CACHE)
# Chipyard's default (variables.mk), then user.home and the proxy block.
export SBT_OPTS := -Dsbt.ivy.home=$(CHIPYARD_ROOT)/.ivy2 \
  -Dsbt.global.base=$(CHIPYARD_ROOT)/.sbt \
  -Dsbt.boot.directory=$(CHIPYARD_ROOT)/.sbt/boot/ -Dsbt.color=always \
  -Dsbt.supershell=false -Dsbt.server.forcestart=true \
  -Duser.home=$(CHIPYARD_SBT_HOME) \
  $(if $(filter 1,$(DORA_SBT_ONLINE)),,$(OFFLINE_SBT_PROXY))

# Defining offline-sbt-check must not make it the includer's default goal.
_offline_sbt_default_goal := $(.DEFAULT_GOAL)

.PHONY: offline-sbt-check
offline-sbt-check:
	@if [ "$(DORA_SBT_ONLINE)" != 1 ] && [ ! -d "$(DORA_COURSIER_CACHE)" ]; then \
	  echo "offline-sbt.mk: DORA_COURSIER_CACHE=$(DORA_COURSIER_CACHE) is not a directory;" \
	    "point it at the pinned Coursier cache (or set DORA_SBT_ONLINE=1 to let sbt fill it)." >&2; \
	  exit 1; \
	fi
	@mkdir -p "$(CHIPYARD_SBT_HOME)"

.DEFAULT_GOAL := $(_offline_sbt_default_goal)
