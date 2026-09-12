#!/usr/bin/env bash
#
# Builds the PopCraft standalone SWFs by driving mxmlc directly against source checkouts of
# every dependency. There is no ant, no project-include.xml and no prebuilt SWC.
#
#   ./build.sh              build both SWFs
#   ./build.sh standalone   build bin/PopCraft.swf only
#   ./build.sh offline      build bin/PopCraft-offline.swf only
#
# Every path is derived from this script's own location, so the checkout can live anywhere.
# The dependency checkouts are expected under ./deps, or wherever CORPSE_CRAFT_DEPS points.
# README.md lists the revision each one has to be pinned to.

set -euo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DEPS=${CORPSE_CRAFT_DEPS:-$HERE/deps}

FLEX=$DEPS/flexsdk
PC=$DEPS/whirled-projects/games/popcraft
OUTDIR=$HERE/bin
LEVELDIR=$HERE/levels

PLAYERGLOBAL_DIR=$FLEX/frameworks/libs/player
PLAYERGLOBAL_SWC=$PLAYERGLOBAL_DIR/32.0/playerglobal.swc

# mxmlc resolves the {playerglobalHome} token in frameworks/flex-config.xml from this variable
# and from nothing else. The +playerglobalHome= command-line form is accepted and then ignored,
# leaving the token unexpanded in the error message.
export PLAYERGLOBAL_HOME=$PLAYERGLOBAL_DIR

SOURCE_ROOTS=(
    "$PC/src"
    "$DEPS/flashbang/src/main/as"
    "$DEPS/aspirin/src/main/as"
    "$DEPS/narya/aslib/src/main/as"
    "$DEPS/whirled-sdk/libraries/whirled/src/main/as"
    "$DEPS/whirled-sdk/contrib/src/as"
)

fail () {
    echo "build.sh: $1" >&2
    exit 1
}

preflight () {
    local root
    local broken=0

    for root in "${SOURCE_ROOTS[@]}"; do
        if [ ! -d "$root" ]; then
            echo "build.sh: missing source root $root" >&2
            broken=1
        fi
    done
    [ -f "$DEPS/whirled-sdk/lib/corelib.swc" ] || {
        echo "build.sh: missing $DEPS/whirled-sdk/lib/corelib.swc" >&2
        broken=1
    }
    [ -f "$FLEX/lib/mxmlc.jar" ] || {
        echo "build.sh: missing $FLEX/lib/mxmlc.jar" >&2
        broken=1
    }
    if [ "$broken" -ne 0 ]; then
        fail "check out the dependencies under $DEPS, or point CORPSE_CRAFT_DEPS elsewhere (see README.md)"
    fi

    if [ ! -f "$PLAYERGLOBAL_SWC" ]; then
        fail "missing $PLAYERGLOBAL_SWC (see the Flex SDK section of README.md)"
    fi

    # env.properties in the SDK root outranks PLAYERGLOBAL_HOME, and a stale one fails the
    # build with a path that appears nowhere in this script.
    if [ -f "$FLEX/env.properties" ] &&
       ! grep -qxF "env.PLAYERGLOBAL_HOME=$PLAYERGLOBAL_DIR" "$FLEX/env.properties"; then
        fail "$FLEX/env.properties overrides PLAYERGLOBAL_HOME with another path; delete it, or set it to env.PLAYERGLOBAL_HOME=$PLAYERGLOBAL_DIR"
    fi
}

build () {
    local entry=$1
    local out=$2

    echo "==> building $out from $entry.as"
    java -Xmx1500M -jar "$FLEX/lib/mxmlc.jar" \
        +flexlib="$FLEX/frameworks" \
        -target-player=32.0 \
        -swf-version=19 \
        -static-link-runtime-shared-libraries=true \
        -use-network=false \
        -compiler.headless-server \
        -compiler.source-path+="${SOURCE_ROOTS[0]}" \
        -compiler.source-path+="${SOURCE_ROOTS[1]}" \
        -compiler.source-path+="${SOURCE_ROOTS[2]}" \
        -compiler.source-path+="${SOURCE_ROOTS[3]}" \
        -compiler.source-path+="${SOURCE_ROOTS[4]}" \
        -compiler.source-path+="${SOURCE_ROOTS[5]}" \
        -compiler.library-path+="$DEPS/whirled-sdk/lib/corelib.swc" \
        -file-specs "$PC/src/popcraft/$entry.as" \
        -output "$OUTDIR/$out"
}

# PopCraft.swf reads its levels from ../levels at runtime: LevelManager.as hardcodes
# LEVELS_DIR = "../levels". They are game data rather than build output, so they are copied
# out of the game checkout instead of being kept in this repository.
sync_levels () {
    echo "==> syncing levels from $PC/levels"
    mkdir -p "$LEVELDIR"
    cp -f "$PC"/levels/*.xml "$LEVELDIR/"
}

preflight
mkdir -p "$OUTDIR"

case "${1:-both}" in
    standalone)
        sync_levels
        build PopCraft_Standalone PopCraft.swf
        ;;
    offline)
        build PopCraft_Offline PopCraft-offline.swf
        ;;
    both)
        sync_levels
        build PopCraft_Standalone PopCraft.swf
        build PopCraft_Offline PopCraft-offline.swf
        ;;
    *)
        echo "usage: $0 [standalone|offline|both]" >&2
        exit 2
        ;;
esac
