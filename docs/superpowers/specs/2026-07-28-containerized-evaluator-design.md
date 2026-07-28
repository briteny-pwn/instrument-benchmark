# Containerized Evaluator Design

Date: 2026-07-28

## Decision

The official benchmark path will run the complete trusted evaluator inside a
Docker container on native Linux Docker Engine. The evaluator container will
retain PyVISA/pyvisa-sim, hidden worlds, `DUTWorld`, the gateway, journal,
oracle, constraints, scoring, and report generation. For every world it will
use the host Docker daemon to create a separate hardened sibling candidate
container through the existing `DockerCandidateBackend`.

The orchestrator repository owns the evaluator-image Dockerfile, offline
dependency wheelhouse manifest, build policy, container launch policy, and
outer-container evidence. The instance repository continues to own only the
candidate image contract. The evaluator repository continues to own private
evaluation code and candidate-container behavior.

## Trust boundary

Trusted components are the orchestrator, evaluator and instance checkouts, the
evaluator image build inputs, Docker daemon, Linux kernel, and the evaluator
container. Candidate source and every sibling candidate container are
untrusted.

Mounting `/var/run/docker.sock` gives the trusted evaluator container effective
control over the host Docker daemon. This is an accepted first-version tradeoff.
The socket must never be mounted into a candidate container, exposed through
the gateway, or included in a candidate-visible directory.

The first version supports native Linux Docker Engine and `linux/amd64` only.
Docker Desktop compatibility and remote Docker daemons are out of scope.

## Runtime topology

```text
Linux host / orchestrator
├── builds evaluator image from evaluator checkout + offline wheelhouse
├── creates a unique host shared-run-root
├── mounts request, instance, candidate, and shared-run-root
└── mounts /var/run/docker.sock
                    │
                    ▼
Trusted evaluator container
├── PyVISA / pyvisa-sim
├── hidden worlds / DUTWorld / gateway / journal
├── oracle / constraints / scoring
└── DockerCandidateBackend
                    │ host Docker daemon
                    ▼
One untrusted sibling candidate container per world
├── network none / read-only / non-root
├── visible workspace + candidate + bootstrap only
├── run-scoped gateway socket
└── bounded output directory and tmpfs
```

The shared run root is bind-mounted at the same absolute path on the host and
inside the evaluator container. This invariant is mandatory: bind sources
passed by the evaluator to the host Docker daemon must be host-resolvable paths.
All per-world workspace, gateway, output and temporary directories used by the
sibling runner must be created below this root.

## Evaluator image build

Every official run builds the evaluator image locally. The orchestrator stages
a temporary build context containing:

- the evaluator checkout at its validated Git commit, excluding `.git`, build
  outputs, caches and reports;
- the orchestrator-owned evaluator Dockerfile;
- an offline `linux/amd64`, CPython 3.11 wheelhouse for evaluator dependencies;
- a manifest containing the SHA-256 and size of every staged wheel and build
  input.

The build uses `docker build --network=none --platform=linux/amd64`. The base
image is pinned by digest. Dependency installation uses only the staged
wheelhouse with `pip --no-index --require-hashes`; no package index or runtime
network is permitted. The resulting image contains evaluator code and private
package data, but no instance checkout, candidate, Git metadata, prior report,
or host path.

The orchestrator records the Dockerfile digest, build-context manifest digest,
evaluator Git commit, image ID/digest, platform and effective image user.

## Outer evaluator container contract

The orchestrator replaces its official host `python -m
instrument_benchmark_evaluator.cli` invocation with `docker create` plus
`docker start --attach`. The outer evaluator container uses:

```text
--network none
--read-only
--cap-drop ALL
--security-opt no-new-privileges
--pids-limit 256
--memory 2g
--memory-swap 2g
--cpus 2.0
--stop-timeout 2
```

It runs as a non-root fixed UID/GID. The orchestrator adds the host Docker
socket GID as a supplementary group so the evaluator can access the daemon
without running as root. `/tmp` is a bounded tmpfs. The Docker socket is the
only privileged mount.

Mounts are explicit and minimal:

- evaluator request: read-only;
- instance root: read-only, at the same absolute host/container path;
- candidate file: read-only, at the same absolute host/container path;
- shared run root: read-write, at the same absolute host/container path;
- report directory: read-write and confined below the shared run root;
- Docker socket: read-write, evaluator only.

The evaluator request continues to use protocol version 1 candidate fields and
adds `shared_run_root`. All paths in the request are container-visible absolute
paths. `run_world()` uses this supplied root instead of an internal
`TemporaryDirectory` when the official container backend is active.

The host subprocess evaluator invocation remains available only as a unit-test
fixture. It is not selectable in the official run schema or validation path.

## Data flow

1. The orchestrator validates repository provenance, instance hashes and the
   evaluator/instance protocol relationship.
2. It stages and hashes the evaluator build context, builds the image offline,
   and verifies image metadata.
3. It creates a unique shared run root and writes a bounded request there.
4. It creates the hardened evaluator container with identical-path mounts and
   the Docker socket supplementary group.
5. The evaluator loads private worlds and, per world, creates the host-visible
   workspace, gateway and output directories below the shared root.
6. Existing `DockerCandidateBackend` creates one hardened sibling candidate
   container per world and records candidate container evidence.
7. The evaluator performs oracle reconstruction, constraints, scoring and
   aggregation, then writes the evaluator report below the shared root.
8. The orchestrator inspects and removes the evaluator container, validates the
   report as a bounded regular non-symlink file, and adds outer-container image,
   runtime and cleanup evidence to the final report.
9. The shared root and any evaluator-owned stale containers are removed in a
   scoped `finally` path.

## Failure classification and cleanup

Candidate statuses remain unchanged: `completed`, `candidate_failure`,
`candidate_timeout`, `candidate_oom`, `output_limit`, `invalid_result`, and
`invalid_submission`.

Outer evaluator build, Docker create/start/inspect, malformed report, missing
report, evaluator timeout, evaluator OOM, or daemon failure are infrastructure
failures. They never count as candidate capability failures and set
`infrastructure_valid: false` and `retry_eligible: true`.

Cleanup order is deterministic:

1. stop/kill the outer evaluator container if still running;
2. remove sibling candidate containers scoped by run-owner labels;
3. inspect and remove the outer evaluator container;
4. remove the run-scoped evaluator image tag while retaining content-addressed
   cache layers according to normal Docker policy;
5. remove the shared run root after report/evidence collection.

Cleanup never filters by broad image or container names. Every resource carries
an unguessable run ID plus evaluator-owned labels. Failure to remove a container
is recorded as infrastructure evidence and fails the official validation run.

## Evidence and report changes

The final orchestration report adds `evaluator_container` with:

- image ID/digest, Dockerfile SHA-256 and build-manifest SHA-256;
- evaluator repository commit;
- container ID, create/start/finish timestamps and exit/OOM status;
- normalized network, rootfs, user, groups, capabilities, security options,
  limits and mounts;
- stdout/stderr byte counts and SHA-256;
- cleanup outcome and Docker Engine version.

Existing per-world `container_evidence` remains candidate-container evidence.
The two objects must not be merged because they describe different trust
domains. Capability score and gates remain unchanged; outer runtime evidence
affects infrastructure validity only.

## Tests and acceptance criteria

Unit tests must cover build-context exclusion and hashes, offline wheel
manifest validation, exact Docker arguments, socket group propagation,
identical-path mount validation, bounded outer output, report file safety,
failure classification and scoped cleanup.

Linux Docker integration tests must prove:

- evaluator image builds with build network disabled;
- evaluator container has no network, a read-only root, no capabilities and a
  non-root UID while retaining Docker socket access through its group;
- evaluator can create sibling candidates, but candidates cannot read the
  Docker socket, evaluator code, hidden worlds, oracle, journal or Git data;
- gateway socket mounts work across the outer-container/host-daemon boundary;
- reference solution strict-passes all nine fixed and ten repeated worlds;
- adversarial candidates fail their intended gates;
- evaluator timeout, OOM, malformed report and unavailable daemon are reported
  as infrastructure failures;
- no evaluator container, candidate container, socket, session, shared
  directory or run-owned tag remains after success or failure;
- semantic world reports match the current Docker-candidate-runner baseline.

Official CI runs only the evaluator-container path on Ubuntu 24.04. A clean CI
run, `git diff --check`, all repository unit suites and all Docker integration
suites are required for acceptance.

## Migration

Implementation starts from the existing `feature/docker-candidate-runner`
branches in the instance, evaluator and orchestrator repositories. First verify
those branches unchanged. Then add outer image/build support to the
orchestrator, add shared-root support to the evaluator request/run lifecycle,
switch official orchestration to the outer container, extend evidence/schema,
and finally update Linux CI and documentation.

