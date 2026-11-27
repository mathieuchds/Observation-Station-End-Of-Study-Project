#!/usr/bin/env bash
set -euo pipefail

root_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
remote=guma@100.109.194.50
ssh_command='ssh -i ~/.ssh/gumapi5_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=8'
rsync_options=(--times --perms --mkpath --delay-updates --itemize-changes)

if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    printf 'Usage : %s [--dry-run] [dossier ...]\n' "${0##*/}"
    printf 'Projet par défaut : servomotor_monitoring. Chaque dossier doit contenir un fichier .deploy-files.\n'
    exit 0
fi

if [[ ${1:-} == --dry-run ]]; then
    rsync_options+=(--dry-run)
    shift
fi

if (( $# == 0 )); then
    set -- servomotor_monitoring
fi

for project in "$@"; do
    project=${project%/}
    if [[ ! $project =~ ^[[:alnum:]_][[:alnum:]_.-]*$ ]]; then
        printf 'Dossier de projet invalide : %s\n' "$project" >&2
        exit 1
    fi

    source_dir=$root_dir/$project
    if [[ ! -d $source_dir || -L $source_dir || ! -f $source_dir/.deploy-files || -L $source_dir/.deploy-files ]]; then
        printf 'Liste .deploy-files introuvable dans %s\n' "$source_dir" >&2
        exit 1
    fi

    files=()
    while IFS= read -r path || [[ -n $path ]]; do
        [[ -z $path || $path == \#* ]] && continue
        if [[ ! -f $source_dir/$path || $(realpath -- "$source_dir/$path") != "$source_dir/$path" ]]; then
            printf 'Fichier de déploiement invalide dans %s : %s\n' "$project" "$path" >&2
            exit 1
        fi
        files+=("$path")
    done < "$source_dir/.deploy-files"

    if (( ${#files[@]} == 0 )); then
        printf 'Aucun fichier de déploiement dans %s/.deploy-files\n' "$project" >&2
        exit 1
    fi

    printf '%s → %s:~/%s/\n' "$project" "$remote" "$project"
    printf '%s\0' "${files[@]}" |
        rsync "${rsync_options[@]}" --from0 --files-from=- -e "$ssh_command" -- "$source_dir/" "$remote:$project/"
done
