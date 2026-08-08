-- web/sql/grant-webapp.sql -- the portal's MySQL user. Run once, as root.
--
--   set -a; . /srv/wow/wowserver/deploy/.env; set +a
--   docker compose -f /srv/wow/wowserver/deploy/docker-compose.yml exec -T mysql \
--     mysql --defaults-extra-file=/etc/mysql/backup.cnf \
--     -e "SET @pw := '$PORTAL_DB_PASSWORD';" \
--     < /srv/wow/wowserver/web/sql/grant-webapp.sql
--
-- ^ that shape does not work, because MySQL cannot use a user variable in a CREATE
-- USER. Substitute the password instead, and keep it off the command line:
--
--   set -a; . /srv/wow/wowserver/deploy/.env; set +a
--   sed "s/__PORTAL_DB_PASSWORD__/$PORTAL_DB_PASSWORD/" \
--     /srv/wow/wowserver/web/sql/grant-webapp.sql \
--   | docker compose -f /srv/wow/wowserver/deploy/docker-compose.yml exec -T mysql \
--       mysql --defaults-extra-file=/etc/mysql/backup.cnf
--
-- The password is piped on stdin, never in argv, for the same reason
-- deploy/mysql-backup.cnf exists: container processes are visible in `ps` on the host.
-- Generate it the way deploy/.env.example says — [A-Za-z0-9] only, so it cannot break
-- an option file or a connection string.
--
-- WHY A SEPARATE USER AT ALL
-- The `acore` user the game servers use has ALL PRIVILEGES on four schemas. If the
-- portal authenticated as `acore`, then any injection, any mistake in a query, any
-- future feature written in a hurry could change a password, promote an account to
-- administrator or delete a character. This user physically cannot: SELECT is the only
-- verb it holds. That is the difference between a bug and an incident, and it costs one
-- CREATE USER.

-- Host is '%' rather than a literal address: on a Compose network the portal's IP is
-- assigned by Docker and changes whenever the container is recreated. The user is
-- reachable only from that network — MySQL publishes no port to the host in
-- deploy/docker-compose.yml — so '%' is not the exposure it would be on a public server.
CREATE USER IF NOT EXISTS 'acore_web'@'%' IDENTIFIED BY '__PORTAL_DB_PASSWORD__';

-- Idempotent: re-running this file after a password rotation updates the existing user
-- instead of failing on IF NOT EXISTS having done nothing.
ALTER USER 'acore_web'@'%' IDENTIFIED BY '__PORTAL_DB_PASSWORD__';

-- Start from nothing, so re-running after someone has widened the grant by hand puts
-- it back. REVOKE ALL is not an error when there is nothing to revoke.
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'acore_web'@'%';

-- Exactly two schemas, exactly one verb.
--
-- Schema-wide rather than table-by-table because the portal is meant to grow: an
-- account page that later wants achievements or guild membership should not need a
-- root password to add a table to the grant. SELECT on the whole schema is still a
-- much smaller blast radius than the game's ALL PRIVILEGES, and neither schema holds
-- anything the account owner is not entitled to see about themselves.
--
-- acore_auth  : account (username, salt, verifier, joindate, last_login, expansion),
--               account_access (gmlevel), realmlist (name, address, port).
-- acore_world : deliberately NOT granted. Nothing the portal shows comes from it.
-- acore_playerbots : deliberately NOT granted.
GRANT SELECT ON `acore_auth`.*       TO 'acore_web'@'%';
GRANT SELECT ON `acore_characters`.* TO 'acore_web'@'%';

FLUSH PRIVILEGES;

-- Verify — this should print exactly the two GRANT SELECT lines above plus USAGE:
--   SHOW GRANTS FOR 'acore_web'@'%';
