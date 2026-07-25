# Acceptance checklist

## Structural

- [ ] Capsule and profile selected.
- [ ] Runner selected or explicitly left unbound.
- [ ] All required objects verified.
- [ ] Save selection receipt created.
- [ ] Destination is local and validated.
- [ ] Critical vault seals unchanged.

## Functional

- [ ] Canonical launch succeeds.
- [ ] Steam is not started.
- [ ] Existing save loads when selected.
- [ ] No save is present when the clean baseline is selected.
- [ ] DLC is recognized and real DLC content loads.
- [ ] Video works.
- [ ] Audio works.
- [ ] Controller input works.
- [ ] Hotplug works when relevant.
- [ ] Network policy is effective.
- [ ] Normal exit succeeds.
- [ ] Relocation succeeds.
- [ ] Clean restoration succeeds.

## Backend-specific

### Bottles

- [ ] Preserved Bottles backend matches.
- [ ] Selected runner is installed in Bottles.
- [ ] Derived bottle source passes preflight checks.
- [ ] Deployment completes.
- [ ] Temporary heavy source is removed only after success.

### Direct-Wine

- [ ] Each dependency appears once in playable layout.
- [ ] Prefix operations complete.
- [ ] Runner path is valid.
- [ ] Launcher uses relative paths.
- [ ] Selected save set is restored atomically.

### Windows export

- [ ] Export contains no Wine prefix or Linux runner.
- [ ] Save installer targets documented Windows locations.
- [ ] Native Windows launch is tested before verification.
