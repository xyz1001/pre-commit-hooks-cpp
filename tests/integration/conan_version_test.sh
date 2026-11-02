#!/usr/bin/env bash
# Real Git/pre-commit integration; every consumer repository is freshly created.
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
if [[ -z ${TMPDIR:-} && -d /tmp/opencode && -w /tmp/opencode ]]; then TMPDIR=/tmp/opencode; fi
work=$(mktemp -d "${TMPDIR:-/tmp}/conan-version-integration.XXXXXXXX")
keep=${KEEP_TEST_DIR:-0}
cleanup() {
    status=$?
    if [[ $keep == 1 || ( $keep == on-failure && $status != 0 ) ]]; then
        printf 'Integration logs retained: %s\n' "$work"
    else
        rm -rf -- "$work"
    fi
}
trap cleanup EXIT
# Ignore inherited repository/configuration redirects before the first Git call.
for name in ${!GIT_CONFIG_@}; do unset "$name"; done
unset GIT_CONFIG GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE \
    GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_QUARANTINE_PATH \
    GIT_NAMESPACE GIT_SHALLOW_FILE GIT_GRAFT_FILE GIT_REPLACE_REF_BASE \
    GIT_CEILING_DIRECTORIES GIT_DISCOVERY_ACROSS_FILESYSTEM GIT_IMPLICIT_WORK_TREE \
    GIT_ATTR_SOURCE GIT_EXEC_PATH GIT_TEMPLATE_DIR SKIP || true
mkdir -p "$work/home" "$work/cache" "$work/config" "$work/data" "$work/tmp" "$work/empty-template"
export HOME="$work/home" XDG_CACHE_HOME="$work/cache" XDG_CONFIG_HOME="$work/config" XDG_DATA_HOME="$work/data"
export TMPDIR="$work/tmp" PRE_COMMIT_HOME="$work/pre-commit-home"
# Keep network, proxy and certificate settings, but discard pip/virtualenv
# installation targets, user configuration and caches inherited from the caller.
for name in ${!PIP_@}; do
    case $name in
        PIP_INDEX_URL|PIP_EXTRA_INDEX_URL|PIP_TRUSTED_HOST|PIP_CERT|PIP_CLIENT_CERT|PIP_PROXY|PIP_TIMEOUT|PIP_RETRIES) ;;
        *) unset "$name" ;;
    esac
done
for name in ${!VIRTUALENV_@}; do unset "$name"; done
unset PYTHONPATH PYTHONHOME PYTHONUSERBASE PYTHONPYCACHEPREFIX VIRTUAL_ENV || true
export PIP_CONFIG_FILE=/dev/null PIP_CACHE_DIR="$work/pip-cache"
export VIRTUALENV_OVERRIDE_APP_DATA="$work/virtualenv-app-data"
export GIT_TEMPLATE_DIR="$work/empty-template"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0
export GIT_AUTHOR_NAME='Integration Test' GIT_AUTHOR_EMAIL='test@example.invalid'
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
export GIT_SEQUENCE_EDITOR=true GIT_EDITOR=true

fail() { printf 'FAIL: %s (logs: %s)\n' "$*" "$work" >&2; exit 1; }
contains() { grep -Fq -- "$2" "$1" || fail "missing '$2' in $1"; }
clean() { [[ -z $(git status --porcelain=v1 --untracked-files=all) ]] || fail 'consumer worktree is not clean'; }
run() {
    local label=$1; shift
    local logfile="$TEST_LOG_DIR/$label.log"
    local before after file
    before=$(find "$TEST_LOG_DIR" -maxdepth 1 \( -name 'hook-*' -o -name 'mapping-*.exit' \) -type f | sort)
    local result=0
    "$@" >"$logfile.stdout" 2>"$logfile.stderr" || result=$?
    cat "$logfile.stdout" "$logfile.stderr" >"$logfile"
    if (( result != 0 )); then
        printf 'Command failed: %s\n' "$*" >&2; cat "$logfile" >&2; fail "$label"
    fi
    if grep -E 'Failed|VERSION CHECK FAILED|conan-version post-rewrite:' "$logfile"; then fail "hook failure in $label"; fi
    after=$(find "$TEST_LOG_DIR" -maxdepth 1 \( -name 'hook-*' -o -name 'mapping-*.exit' \) -type f | sort)
    while IFS= read -r file; do
        [[ -z $file || $(<"$file") == 0 ]] || fail "hook returned nonzero during $label: $file"
    done < <(comm -13 <(printf '%s\n' "$before") <(printf '%s\n' "$after"))
}
version() { printf 'class Recipe:\n    version = "%s"\n' "$1" >"${VERSION_FILE:-conanfile.py}"; }
assert_version() { grep -Fxq "    version = \"$1\"" "${VERSION_FILE:-conanfile.py}" || fail "expected version $1"; }
assert_subject() { [[ $(git log -1 --format=%s) == "$1" ]] || fail "unexpected subject: $(git log -1 --format=%s)"; }
commit() {
    local label=$1 message=$2
    git add -- .
    run "$label" git commit -m "$message"
    contains "$TEST_LOG_DIR/$label.log" 'check version'
    contains "$TEST_LOG_DIR/$label.log" 'Passed'
}

# Snapshot the current working tree, not HEAD or an installed pre-commit cache.
mkdir -p "$work/package/hooks"
cp "$root"/hooks/*.py "$work/package/hooks/"
cp "$root/.pre-commit-hooks.yaml" "$root/setup.py" "$root/setup.cfg" "$root/README.md" "$root/LICENSE" "$work/package/"
git -C "$work/package" init -q -b main
git -C "$work/package" config commit.gpgsign false
git -C "$work/package" add .
git -C "$work/package" commit -qm 'integration snapshot'
revision=$(git -C "$work/package" rev-parse HEAD)

new_repo() {
    local name=$1
    export VERSION_FILE=${3:-conanfile.py}
    mkdir -p "$work/$name" "$work/logs/$name"
    cd "$work/$name"
    export TEST_LOG_DIR="$work/logs/$name"
    git init -q -b main
    git config user.name 'Integration Test'
    git config user.email 'test@example.invalid'
    git config commit.gpgsign false
    git config tag.gpgsign false
    git config rebase.updateRefs false
    cat >.pre-commit-config.yaml <<EOF
repos:
  - repo: file://$work/package
    rev: $revision
    hooks:
      - id: check-version
        args: [--version-file=$VERSION_FILE, '--version-regex=^\s*version\s*=\s*["''](\d+(?:\.\d+)+)["'']', --fix-commit-message]
      - id: conan-version-merge-driver
        args: ['--version-regex=^\s*version\s*=\s*["''](\d+(?:\.\d+)+)["'']']
      - id: conan-version-post-rewrite
        args: [--version-file=$VERSION_FILE, '--version-regex=^\s*version\s*=\s*["''](\d+(?:\.\d+)+)["'']']
EOF
    printf '%s merge=conan-version\n' "$VERSION_FILE" >.gitattributes
    git config merge.conan-version.driver 'pre-commit run conan-version-merge-driver --hook-stage manual --files %O %A %B'
    for type in commit-msg post-commit post-rewrite; do
        run "install-$type" pre-commit install --hook-type "$type"
    done
    for type in commit-msg post-commit; do
        mv ".git/hooks/$type" ".git/hooks/$type-pre-commit"
        cat >".git/hooks/$type" <<'EOF'
#!/usr/bin/env bash
set -u
type=${0##*/}
file=$(mktemp "$TEST_LOG_DIR/hook-$type.XXXXXXXX")
"$0-pre-commit" "$@"
result=$?
printf '%s\n' "$result" >"$file"
exit "$result"
EOF
        chmod +x ".git/hooks/$type"
    done
    # Preserve and execute the installed pre-commit hook, recording Git's mappings.
    mv .git/hooks/post-rewrite .git/hooks/post-rewrite-pre-commit
    cat >.git/hooks/post-rewrite <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
input=$(mktemp "$TEST_LOG_DIR/mapping-$1.XXXXXXXX")
cat >"$input"
if [[ -f .git/rebase-merge/done ]]; then cp .git/rebase-merge/done "$input.done"; fi
if [[ -f .git/rebase-merge/rewritten-list ]]; then cp .git/rebase-merge/rewritten-list "$input.rewritten-list"; fi
set +e
.git/hooks/post-rewrite-pre-commit "$@" <"$input"
result=$?
set -e
printf '%s\n' "$result" >"$input.exit"
exit "$result"
EOF
    chmod +x .git/hooks/post-rewrite
    mkdir -p "$(dirname "$VERSION_FILE")"
    version "${2:-1.0.0}"
    commit base "[feature][${2:-1.0.0}] base"
    clean
}

new_repo commit-amend-fixup
version 1.0.1; printf 'one\n' >content.txt
commit ordinary '[feature][9.9.9] ordinary'
assert_version 1.0.1; assert_subject '[feature][1.0.1] ordinary'
printf 'amended\n' >>content.txt; git add content.txt
run amend git commit --amend -m '[feature][9.9.9] amended'
contains "$TEST_LOG_DIR/amend.log" 'check version'; assert_subject '[feature][1.0.1] amended'
printf 'fixup\n' >fixup.txt; git add fixup.txt
run fixup git commit --fixup=HEAD
contains "$TEST_LOG_DIR/fixup.log" 'check version'
assert_subject 'fixup! [feature][1.0.1] amended'; assert_version 1.0.1; clean
printf 'PASS: commit, amend, fixup\n'

new_repo version-increments
for v in 1.0.1 1.1.0 2.0.0; do
    version "$v"; commit "commit-$v" "[feature][9.9.9] version $v"
    assert_version "$v"; assert_subject "[feature][$v] version $v"
done
[[ $(git rev-list --count HEAD) == 4 ]] || fail 'increment history incomplete'
clean
printf 'PASS: first commit and patch/minor/major increments\n'

new_repo four-segments 1.2.3.4
version 1.2.3.5; commit patch '[feature][1.2.3.5] four patch'
version 1.2.4.0; commit minor '[feature][1.2.4.0] four minor'
assert_version 1.2.4.0; assert_subject '[feature][1.2.4.0] four minor'; clean
printf 'PASS: four-segment increments\n'

new_repo staged-version
version 1.0.1; git add conanfile.py; version 8.8.8
run staged git commit -m '[feature][9.9.9] first [7.7.7]' -m 'body [6.6.6]'
contains "$TEST_LOG_DIR/staged.log" 'check version'
assert_subject '[feature][1.0.1] first [7.7.7]'
[[ $(git log -1 --format=%B) == $'[feature][1.0.1] first [7.7.7]\n\nbody [6.6.6]' ]] || fail 'message body/extra version changed'
[[ $(git show HEAD:conanfile.py) == *'version = "1.0.1"'* ]] || fail 'staged version not committed'
assert_version 8.8.8
git restore --worktree conanfile.py; clean
printf 'PASS: staged version, first message tag and body preservation\n'

for kind in missing-version unmatched-regex; do
    new_repo "commit-reject-$kind"
    before=$(git rev-parse HEAD)
    if [[ $kind == missing-version ]]; then
        version 1.0.1; git add conanfile.py; message='missing version'
        error='No version found in commit message'
    else
        printf 'class Recipe:\n    invalid = "1.0.1"\n' >conanfile.py; git add conanfile.py
        message='[feature][1.0.1] unmatched'; error='No version matched in conanfile.py'
    fi
    result=0; git commit -m "$message" >"$TEST_LOG_DIR/reject.stdout" 2>"$TEST_LOG_DIR/reject.stderr" || result=$?
    cat "$TEST_LOG_DIR/reject.stdout" "$TEST_LOG_DIR/reject.stderr" >"$TEST_LOG_DIR/reject.log"
    [[ $result != 0 && $(git rev-parse HEAD) == "$before" ]] || fail 'invalid commit was accepted'
    contains "$TEST_LOG_DIR/reject.log" "$error"
    grep -l '^1$' "$TEST_LOG_DIR"/hook-commit-msg.* >/dev/null || fail 'commit-msg failure status missing'
    git reset -q HEAD -- conanfile.py; git restore conanfile.py; clean
    printf 'PASS: commit-msg rejects %s without changing HEAD\n' "$kind"
done

for kind in unchanged jump no-reset; do
    new_repo "post-commit-$kind" 1.2.3
    case $kind in unchanged) bad=1.2.3;; jump) bad=1.2.5;; no-reset) bad=1.3.1;; esac
    before=$(git rev-parse HEAD); version "$bad"; printf '%s\n' "$kind" >change.txt; git add .
    result=0; git commit -m "[feature][$bad] invalid increment" >"$TEST_LOG_DIR/reject.stdout" 2>"$TEST_LOG_DIR/reject.stderr" || result=$?
    cat "$TEST_LOG_DIR/reject.stdout" "$TEST_LOG_DIR/reject.stderr" >"$TEST_LOG_DIR/reject.log"
    [[ $result == 0 && $(git rev-parse HEAD^) == "$before" ]] || fail 'expected Git to retain invalid commit'
    contains "$TEST_LOG_DIR/reject.log" 'VERSION CHECK FAILED'
    grep -l '^1$' "$TEST_LOG_DIR"/hook-post-commit.* >/dev/null || fail 'post-commit failure status missing'
    assert_version "$bad"; assert_subject "[feature][$bad] invalid increment"; clean
    printf 'KNOWN LIMITATION: post-commit detects %s despite Git success\n' "$kind"
done

new_repo reused-prefix
git branch upstream
version 1.0.1; printf 'one\n' >one.txt; commit first '[feature][1.0.1] first'; first=$(git rev-parse HEAD)
version 1.0.2; printf 'two\n' >two.txt; commit second '[feature][1.0.2] second'; second=$(git rev-parse HEAD)
version 1.0.3; printf 'target\n' >target.txt; commit target '[feature][1.0.3] target'; oldtarget=$(git rev-parse HEAD)
version 1.1.0; printf 'fixup\n' >fixup.txt; git add conanfile.py fixup.txt
run fixup git commit --fixup=HEAD; oldfixup=$(git rev-parse HEAD)
run rebase git rebase -i --autosquash upstream
contains "$TEST_LOG_DIR/rebase.log" 'conan version post rewrite'
contains "$TEST_LOG_DIR/rebase.log" 'Passed'
[[ $(git rev-parse HEAD^) == "$second" && $(git rev-parse HEAD^^) == "$first" ]] || fail 'prefix changed'
[[ $(git rev-list --count upstream..HEAD) == 3 ]] || fail 'fixup not folded'
[[ $(cat fixup.txt) == fixup && $(cat target.txt) == target ]] || fail 'content lost'
assert_version 1.1.0; assert_subject '[feature][1.1.0] target'; clean
mapfile -t maps < <(find "$TEST_LOG_DIR" -maxdepth 1 -name 'mapping-rebase.*' ! -name '*.done' ! -name '*.rewritten-list' ! -name '*.exit')
[[ ${#maps[@]} == 1 && $(wc -l <"${maps[0]}") == 2 ]] || fail 'expected two squash mappings'
[[ $(cat "${maps[0]}.exit") == 0 ]] || fail 'post-rewrite hook failed'
contains "${maps[0]}" "$oldtarget "; contains "${maps[0]}" "$oldfixup "
contains "${maps[0]}.done" "$first"; contains "${maps[0]}.done" "$second"
printf 'PASS: autosquash unchanged prefix and normalization\n'

new_repo diverged
git branch local
version 1.0.1; printf 'upstream\n' >upstream.txt; commit upstream '[feature][1.0.1] upstream'
git checkout -q local
version 1.0.1; printf 'local\n' >local.txt; commit local '[feature][1.0.1] local'; oldlocal=$(git rev-parse HEAD)
printf 'fixup\n' >fixup.txt; git add fixup.txt; run fixup git commit --fixup=HEAD; oldfixup=$(git rev-parse HEAD)
run rebase git rebase -i --autosquash main
contains "$TEST_LOG_DIR/rebase.log" 'conan version post rewrite'; contains "$TEST_LOG_DIR/rebase.log" 'Passed'
[[ $(git rev-parse HEAD^) == $(git rev-parse main) && $(git rev-list --count main..HEAD) == 1 ]] || fail 'unexpected rewritten chain'
[[ $(cat local.txt) == local && $(cat upstream.txt) == upstream && $(cat fixup.txt) == fixup ]] || fail 'content lost'
assert_version 1.0.2; assert_subject '[feature][1.0.2] local'; clean
mapfile -t maps < <(find "$TEST_LOG_DIR" -maxdepth 1 -name 'mapping-rebase.*' ! -name '*.done' ! -name '*.rewritten-list' ! -name '*.exit')
[[ ${#maps[@]} == 1 && $(wc -l <"${maps[0]}") == 2 ]] || fail 'expected full mappings'
[[ $(cat "${maps[0]}.exit") == 0 ]] || fail 'post-rewrite hook failed'
contains "${maps[0]}" "$oldlocal "; contains "${maps[0]}" "$oldfixup "
printf 'PASS: autosquash diverged upstream and complete mappings\n'

for pair in patch-minor minor-patch; do
    new_repo "replay-$pair"
    git branch local
    if [[ $pair == patch-minor ]]; then remote=1.0.1; localversion=1.1.0; final=1.1.0
    else remote=1.1.0; localversion=1.0.1; final=1.1.1; fi
    version "$remote"; printf 'remote\n' >remote.txt; commit remote "[feature][$remote] remote"
    git checkout -q local
    version "$localversion"; printf 'local\n' >local.txt; commit local "[feature][$localversion] local"
    run rebase git rebase -i main
    contains "$TEST_LOG_DIR/rebase.log" 'conan version merge driver'
    contains "$TEST_LOG_DIR/rebase.log" 'conan version post rewrite'
    [[ $(git rev-parse HEAD^) == $(git rev-parse main) ]] || fail 'incorrect replay parent'
    assert_version "$final"; assert_subject "[feature][$final] local"
    [[ $(cat local.txt) == local && $(cat remote.txt) == remote ]] || fail 'replay content lost'
    clean; printf 'PASS: upstream/local %s replay\n' "$pair"
done

new_repo non-version-lines
printf '\nremote = "base"\n\n\n\nlocal = "base"\n' >>conanfile.py
git add conanfile.py; run amend-base git commit --amend --no-edit
git branch local
version 1.0.1; printf '\nremote = "changed"\n\n\n\nlocal = "base"\n' >>conanfile.py
commit remote '[feature][1.0.1] remote'
git checkout -q local
version 1.1.0; printf '\nremote = "base"\n\n\n\nlocal = "changed"\n' >>conanfile.py
commit local '[feature][1.1.0] local'
run rebase git rebase -i main
contains "$TEST_LOG_DIR/rebase.log" 'conan version merge driver'
contains "$TEST_LOG_DIR/rebase.log" 'conan version post rewrite'
grep -Fxq 'remote = "changed"' conanfile.py || fail 'remote non-version line lost'
grep -Fxq 'local = "changed"' conanfile.py || fail 'local non-version line lost'
assert_version 1.1.0; assert_subject '[feature][1.1.0] local'; clean
printf 'PASS: independent non-version lines preserved\n'

for action in continue abort; do
    new_repo "conflict-$action"
    printf 'setting = "base"\n' >>conanfile.py; git add conanfile.py; run amend-base git commit --amend --no-edit
    git branch local
    version 1.0.1; printf 'setting = "remote"\n' >>conanfile.py; commit remote '[feature][1.0.1] remote'
    git checkout -q local
    version 1.0.1; printf 'setting = "local"\n' >>conanfile.py; commit local '[feature][1.0.1] local'
    old=$(git rev-parse HEAD)
    result=0; git rebase -i main >"$TEST_LOG_DIR/conflict.stdout" 2>"$TEST_LOG_DIR/conflict.stderr" || result=$?
    [[ $result != 0 && -n $(git diff --name-only --diff-filter=U) ]] || fail 'expected conflict'
    contains "$TEST_LOG_DIR/conflict.stdout" 'conan version merge driver'
    contains "$TEST_LOG_DIR/conflict.stdout" 'exit code: 1'
    if [[ $action == abort ]]; then
        run abort git rebase --abort
        [[ $(git rev-parse HEAD) == "$old" ]] || fail 'abort did not restore branch'
        assert_version 1.0.1; grep -Fxq 'setting = "local"' conanfile.py || fail 'abort content lost'
    else
        version 1.0.2; printf 'setting = "resolved"\n' >>conanfile.py; git add conanfile.py
        run continue git rebase --continue
        contains "$TEST_LOG_DIR/continue.log" 'conan version post rewrite'
        [[ $(git rev-parse HEAD^) == $(git rev-parse main) ]] || fail 'continue parent wrong'
        assert_version 1.0.2; assert_subject '[feature][1.0.2] local'
        grep -Fxq 'setting = "resolved"' conanfile.py || fail 'resolution lost'
    fi
    clean; printf 'PASS: conflicting non-version line, rebase %s\n' "$action"
done

new_repo multiple-fixups
git branch upstream
version 1.0.1; printf 'a\n' >a.txt; commit first '[feature][1.0.1] first'; first=$(git rev-parse HEAD)
printf 'a1\n' >a1.txt; git add .; run fixup-a1 git commit --fixup="$first"
printf 'a2\n' >a2.txt; git add .; run fixup-a2 git commit --fixup="$first"
version 1.0.2; printf 'b\n' >b.txt; commit second '[feature][1.0.2] second'; second=$(git rev-parse HEAD)
version 1.1.0; printf 'b1\n' >b1.txt; git add .; run fixup-b git commit --fixup="$second"
run rebase git rebase -i --autosquash upstream
contains "$TEST_LOG_DIR/rebase.log" 'conan version post rewrite'
[[ $(git rev-list --count upstream..HEAD) == 2 ]] || fail 'multiple fixups not folded'
[[ $(git log -1 --format=%s HEAD^) == '[feature][1.0.1] first' ]] || fail 'first fixup group incorrect'
for f in a a1 a2 b b1; do [[ $(cat "$f.txt") == "$f" ]] || fail "lost $f"; done
assert_version 1.1.0; assert_subject '[feature][1.1.0] second'; clean
printf 'PASS: multiple fixups and targets, highest bump once\n'

for action in squash reword edit; do
    new_repo "interactive-$action"
    git branch upstream
    version 1.0.1; printf 'one\n' >one.txt; commit first '[feature][1.0.1] first'
    if [[ $action == squash ]]; then
        version 1.1.0; printf 'two\n' >two.txt; commit second '[feature][1.1.0] second'
    fi
    editor="$work/editor-$action.py"
    printf '%s\n' 'from pathlib import Path' 'import sys' 'p = Path(sys.argv[1])' 'lines = p.read_text().splitlines()' >"$editor"
    if [[ $action == squash ]]; then
        printf '%s\n' "lines[1] = lines[1].replace('pick ', 'squash ', 1)" >>"$editor"
    else
        printf '%s\n' "lines[0] = lines[0].replace('pick ', '$action ', 1)" >>"$editor"
    fi
    printf '%s\n' "p.write_text('\\n'.join(lines) + '\\n')" >>"$editor"
    export GIT_SEQUENCE_EDITOR="python3 $editor"
    run rebase git rebase -i upstream
    export GIT_SEQUENCE_EDITOR=true
    if [[ $action == edit ]]; then
        [[ -d .git/rebase-merge ]] || fail 'edit did not stop'
        run continue git rebase --continue
        contains "$TEST_LOG_DIR/continue.log" 'conan version post rewrite'
    else
        contains "$TEST_LOG_DIR/rebase.log" 'conan version post rewrite'
    fi
    [[ $(git rev-list --count upstream..HEAD) == 1 ]] || fail 'interactive result count'
    if [[ $action == squash ]]; then assert_version 1.1.0; assert_subject '[feature][1.1.0] first'
    else assert_version 1.0.1; assert_subject '[feature][1.0.1] first'; fi
    clean; printf 'PASS: interactive %s\n' "$action"
done

new_repo nested-path 1.0.0 recipes/conanfile.py
git branch local
version 1.0.1; printf 'remote\n' >remote.txt; commit remote '[feature][1.0.1] remote'
git checkout -q local
version 1.1.0; printf 'local\n' >local.txt; commit local '[feature][1.1.0] local'
run rebase git rebase -i main
contains "$TEST_LOG_DIR/rebase.log" 'conan version merge driver'
contains "$TEST_LOG_DIR/rebase.log" 'conan version post rewrite'
assert_version 1.1.0; assert_subject '[feature][1.1.0] local'; clean
printf 'PASS: nested version file and single-group regex\n'

for mode in multiple-groups ordinary-merge; do
    new_repo "driver-$mode"
    git branch local
    version 1.0.1; printf 'remote\n' >remote.txt; commit remote '[feature][1.0.1] remote'
    git checkout -q local
    version 1.1.0; printf 'local\n' >local.txt; commit local '[feature][1.1.0] local'
    before=$(git rev-parse HEAD)
    if [[ $mode == multiple-groups ]]; then
        config="$work/multiple-groups.yaml"
        python3 - "$config" <<'EOF'
from pathlib import Path
import sys
text = Path('.pre-commit-config.yaml').read_text()
before, after = text.split('      - id: conan-version-merge-driver\n', 1)
line, rest = after.split('\n', 1)
line = line.replace('(\\d+(?:\\.\\d+)+)', '(\\d+)\\.(\\d+)\\.(\\d+)')
Path(sys.argv[1]).write_text(before + '      - id: conan-version-merge-driver\n' + line + '\n' + rest)
EOF
        git config merge.conan-version.driver "pre-commit run conan-version-merge-driver --config $config --hook-stage manual --files %O %A %B"
        result=0; git rebase -i main >"$TEST_LOG_DIR/reject.stdout" 2>"$TEST_LOG_DIR/reject.stderr" || result=$?
        expected='--version-regex must contain exactly one capture group'
    else
        result=0; git merge main >"$TEST_LOG_DIR/reject.stdout" 2>"$TEST_LOG_DIR/reject.stderr" || result=$?
        expected='only merge-backend rebase is supported'
    fi
    cat "$TEST_LOG_DIR/reject.stdout" "$TEST_LOG_DIR/reject.stderr" >"$TEST_LOG_DIR/reject.log"
    [[ $result != 0 && -n $(git diff --name-only --diff-filter=U) ]] || fail 'expected merge driver rejection'
    contains "$TEST_LOG_DIR/reject.log" "$expected"
    contains "$TEST_LOG_DIR/reject.log" 'Failed'
    contains "$TEST_LOG_DIR/reject.log" 'exit code: 2'
    if [[ $mode == multiple-groups ]]; then run abort git rebase --abort; else run abort git merge --abort; fi
    [[ $(git rev-parse HEAD) == "$before" ]] || fail 'abort did not restore original commit'
    assert_version 1.1.0; assert_subject '[feature][1.1.0] local'; clean
    printf 'PASS: merge driver rejects %s\n' "$mode"
done

new_repo unsupported-rebase-merges
git branch upstream
version 1.0.1; printf 'target\n' >target.txt; commit target '[feature][1.0.1] target'
printf 'fixup\n' >fixup.txt; git add fixup.txt; run fixup git commit --fixup=HEAD
set +e
git rebase -i --rebase-merges --autosquash upstream >"$TEST_LOG_DIR/rebase.log" 2>&1
result=$?
set -e
[[ $result == 0 ]] || fail "expected Git success, got $result"
contains "$TEST_LOG_DIR/rebase.log" 'conan version post rewrite'
contains "$TEST_LOG_DIR/rebase.log" 'Failed'
contains "$TEST_LOG_DIR/rebase.log" 'rebase --rebase-merges is unsupported'
mapfile -t maps < <(find "$TEST_LOG_DIR" -maxdepth 1 -name 'mapping-rebase.*' ! -name '*.done' ! -name '*.rewritten-list' ! -name '*.exit')
[[ ${#maps[@]} == 1 && $(cat "${maps[0]}.exit") != 0 ]] || fail 'expected nonzero post-rewrite hook status'
[[ $(git rev-list --count upstream..HEAD) == 1 && $(cat fixup.txt) == fixup ]] || fail 'negative rebase result unexpected'
[[ $(git rev-parse HEAD^) == $(git rev-parse upstream) ]] || fail 'negative rebase parent unexpected'
assert_version 1.0.1; assert_subject '[feature][1.0.1] target'; clean
printf 'NEGATIVE: unsupported rebase-merges hook failure detected despite Git success\n'

# Record every hook status attributable to each deliberately nonstandard Git call.
capture() {
    local label=$1 before after file result=0; shift
    before=$(find "$TEST_LOG_DIR" -maxdepth 1 \( -name 'hook-*' -o -name 'mapping-*.exit' \) -type f | sort)
    "$@" >"$TEST_LOG_DIR/$label.stdout" 2>"$TEST_LOG_DIR/$label.stderr" || result=$?
    cat "$TEST_LOG_DIR/$label.stdout" "$TEST_LOG_DIR/$label.stderr" >"$TEST_LOG_DIR/$label.log"
    printf '%s\n' "$result" >"$TEST_LOG_DIR/$label.git-exit"
    after=$(find "$TEST_LOG_DIR" -maxdepth 1 \( -name 'hook-*' -o -name 'mapping-*.exit' \) -type f | sort)
    : >"$TEST_LOG_DIR/$label.hooks"
    while IFS= read -r file; do
        [[ -z $file ]] || printf '%s %s\n' "${file##*/}" "$(<"$file")" >>"$TEST_LOG_DIR/$label.hooks"
    done < <(comm -13 <(printf '%s\n' "$before") <(printf '%s\n' "$after"))
    git log --format='%H %s' --reverse >"$TEST_LOG_DIR/$label.history"
    git status --porcelain=v1 >"$TEST_LOG_DIR/$label.status"
}
expect_exit() { [[ $(<"$TEST_LOG_DIR/$1.git-exit") == "$2" ]] || fail "$1 Git exit changed; update expectation"; }
expect_hook() { grep -Eq "^$2[^ ]* $3$" "$TEST_LOG_DIR/$1.hooks" || fail "$1 hook $2 status $3 missing; update expectation"; }
expect_no_failed_hooks() { ! grep -Eq ' [1-9][0-9]*$' "$TEST_LOG_DIR/$1.hooks" || fail "$1 unexpected hook failure"; }
expect_provisional_head() {
    local map old new last=''
    mapfile -t maps < <(find "$TEST_LOG_DIR" -maxdepth 1 -name 'mapping-rebase.*' ! -name '*.done' ! -name '*.rewritten-list' ! -name '*.exit')
    [[ ${#maps[@]} == 1 ]] || fail 'expected exactly one rebase mapping'
    map=${maps[0]}
    while read -r old new; do last=$new; done <"$map"
    [[ -n $last && $(git rev-parse HEAD) == "$last" ]] || fail 'HEAD is not the provisional mapped tip'
}
make_sequence_editor() {
    local action=$1 index=$2
    editor="$work/sequence-${action// /-}-$index.py"
    cat >"$editor" <<EOF
from pathlib import Path
import sys
p = Path(sys.argv[1])
lines = p.read_text().splitlines()
idx = [i for i, line in enumerate(lines) if line.startswith('pick ')][$index]
lines[idx] = lines[idx].replace('pick ', '$action ', 1)
p.write_text('\\n'.join(lines) + '\\n')
EOF
    export GIT_SEQUENCE_EDITOR="python3 $editor"
}

for mode in amend reword fixup-c; do
    new_repo "amend-fixup-$mode"
    git branch upstream
    version 1.0.1; printf 'target\n' >target.txt; commit target '[feature][1.0.1] target'
    target=$(git rev-parse HEAD)
    if [[ $mode != reword ]]; then printf 'extra\n' >extra.txt; git add extra.txt; fi
    fixup_kind=amend; [[ $mode != reword ]] || fixup_kind=reword
    capture create git commit "--fixup=$fixup_kind:$target"
    expect_exit create 0; expect_hook create hook-commit-msg 0; expect_hook create hook-post-commit 1
    contains "$TEST_LOG_DIR/create.log" 'Version not incremented: 1.0.1 -> 1.0.1'
    [[ $(git rev-parse HEAD^) == "$target" ]] || fail 'amend fixup commit not created'
    assert_subject 'amend! [feature][1.0.1] target'
    if [[ $mode == fixup-c ]]; then
        make_sequence_editor 'fixup -c' 1
        message_editor="$work/fixup-message.py"
        printf '%s\n' 'from pathlib import Path' 'import sys' "Path(sys.argv[1]).write_text('[feature][1.0.1] edited\\n')" >"$message_editor"
        export GIT_EDITOR="python3 $message_editor"
        capture rebase git rebase -i upstream
    else
        capture rebase git rebase -i --autosquash upstream
    fi
    export GIT_SEQUENCE_EDITOR=true GIT_EDITOR=true
    expect_exit rebase 0; expect_hook rebase mapping-rebase 0; expect_no_failed_hooks rebase
    contains "$TEST_LOG_DIR/rebase.log" 'conan version post rewrite'
    mapfile -t maps < <(find "$TEST_LOG_DIR" -maxdepth 1 -name 'mapping-rebase.*.done')
    [[ ${#maps[@]} == 1 ]] || fail 'fixup rebase todo evidence missing'
    if [[ $mode == fixup-c ]]; then contains "${maps[0]}" 'fixup -c '; else contains "${maps[0]}" 'fixup -C '; fi
    [[ $(git rev-list --count upstream..HEAD) == 1 && $(git rev-parse HEAD^) == $(git rev-parse upstream) ]] || fail 'fixup group not folded'
    if [[ $mode == fixup-c ]]; then assert_subject '[feature][1.0.1] edited'; else assert_subject '[feature][1.0.1] target'; fi
    [[ $mode == reword || $(<extra.txt) == extra ]] || fail 'fixup content lost'
    assert_version 1.0.1; clean
    printf 'KNOWN LIMITATION: %s fixup creation reports post-commit failure; rebase succeeds\n' "$mode"
done

new_repo amend-message-no-version
version 1.0.1; commit target '[feature][1.0.1] target'; target=$(git rev-parse HEAD)
printf 'extra\n' >extra.txt; git add extra.txt
message_editor="$work/no-version-message.py"
printf '%s\n' 'from pathlib import Path' 'import sys' "Path(sys.argv[1]).write_text('amend! no version\\n')" >"$message_editor"
export GIT_EDITOR="python3 $message_editor"
capture create git commit "--fixup=amend:$target"
export GIT_EDITOR=true
expect_exit create 1; expect_hook create hook-commit-msg 1
contains "$TEST_LOG_DIR/create.log" 'No version found in commit message'
[[ $(git rev-parse HEAD) == "$target" ]] || fail 'invalid amend fixup created commit'
! grep -q '^hook-post-commit' "$TEST_LOG_DIR/create.hooks" || fail 'post-commit ran after rejection'
printf 'NEGATIVE: amend fixup without version rejected before commit\n'

for mode in middle prefix tail; do
    new_repo "drop-$mode"
    git branch upstream
    for n in 1 2 3; do version "1.0.$n"; printf '%s\n' "$n" >"$n.txt"; commit "commit-$n" "[feature][1.0.$n] commit $n"; done
    old=$(git rev-parse HEAD)
    case $mode in prefix) index=0;; middle) index=1;; tail) index=2;; esac
    make_sequence_editor drop "$index"
    capture rebase git rebase -i --force-rebase upstream
    export GIT_SEQUENCE_EDITOR=true
    if [[ $mode == tail ]]; then
        expect_exit rebase 0; expect_hook rebase mapping-rebase 1
        contains "$TEST_LOG_DIR/rebase.log" 'mapped old commits are not the complete orig-head interval'
        expect_provisional_head
        [[ $(git rev-list --count upstream..HEAD) == 2 && $(git rev-parse HEAD) != "$old" ]] || fail 'tail provisional history changed'
        assert_version 1.0.2; assert_subject '[feature][1.0.2] commit 2'; clean
    else
        expect_exit rebase 1
        contains "$TEST_LOG_DIR/rebase.log" 'ours version is lower than base version'
        contains "$TEST_LOG_DIR/rebase.log" 'exit code: 2'
        [[ $(git diff --name-only --diff-filter=U) == conanfile.py ]] || fail 'drop conflict changed'
        [[ $(git rev-parse main) == "$old" ]] || fail 'drop changed original branch'
        ! grep -q '^mapping-rebase' "$TEST_LOG_DIR/rebase.hooks" || fail 'unexpected post-rewrite after conflict'
    fi
    printf 'KNOWN LIMITATION: drop %s is unsupported (see recorded Git/hook status)\n' "$mode"
done

new_repo independent-no-bump
git branch upstream
version 1.0.1; commit target '[feature][1.0.1] target'
before=$(git rev-parse HEAD); printf 'extra\n' >extra.txt; git add extra.txt
capture create git commit -m '[feature][1.0.1] no bump'
expect_exit create 0; expect_hook create hook-commit-msg 0; expect_hook create hook-post-commit 1
contains "$TEST_LOG_DIR/create.log" 'Version not incremented: 1.0.1 -> 1.0.1'
[[ $(git rev-parse HEAD^) == "$before" ]] || fail 'no-bump commit was not created'
capture rebase git rebase -i --force-rebase upstream
expect_exit rebase 0; expect_hook rebase mapping-rebase 1
contains "$TEST_LOG_DIR/rebase.log" 'each rewritten group must contain a version bump'
expect_provisional_head
[[ $(git rev-list --count upstream..HEAD) == 2 ]] || fail 'no-bump provisional history changed'
assert_subject '[feature][1.0.1] no bump'; assert_version 1.0.1; clean
printf 'KNOWN LIMITATION: no-bump commit and rewrite hooks fail while Git returns success\n'

new_repo reword-invalid-regex
python3 - <<'EOF'
from pathlib import Path
p = Path('.pre-commit-config.yaml')
text = p.read_text()
lines = text.splitlines()
for i, line in enumerate(lines):
    if 'id: conan-version-post-rewrite' in line:
        lines[i + 1] = lines[i + 1][:-1] + ", '--commit-message-regex=^\\[feature\\]\\[.*\\] .+']"
        break
else:
    raise SystemExit('post-rewrite config missing')
p.write_text('\n'.join(lines) + '\n')
EOF
git add .pre-commit-config.yaml; run configure git commit --amend --no-edit
git branch upstream
version 1.0.1; commit first '[feature][1.0.1] first'
version 1.0.2; commit second '[feature][1.0.2] second'
make_sequence_editor reword 1
message_editor="$work/invalid-regex-message.py"
printf '%s\n' 'from pathlib import Path' 'import sys' "Path(sys.argv[1]).write_text('[bad][1.0.2] edited\\n')" >"$message_editor"
export GIT_EDITOR="python3 $message_editor"
capture rebase git rebase -i --force-rebase upstream
export GIT_SEQUENCE_EDITOR=true GIT_EDITOR=true
expect_exit rebase 0; expect_hook rebase mapping-rebase 1
contains "$TEST_LOG_DIR/rebase.log" 'rebuilt commit message violates --commit-message-regex'
expect_provisional_head
[[ $(git rev-list --count upstream..HEAD) == 2 ]] || fail 'regex provisional history changed'
assert_subject '[bad][1.0.2] edited'; assert_version 1.0.2; clean
printf 'KNOWN LIMITATION: reword regex rejected by hook but Git keeps provisional history\n'

printf '正常/预期拒绝: 22 checks passed; 已知限制: 11 reproduced (not functional success). Logs: %s\n' "$work/logs"
