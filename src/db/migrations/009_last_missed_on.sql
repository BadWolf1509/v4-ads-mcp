-- 009_last_missed_on.sql
-- `missed_syncs` contava uma ausência por EXECUÇÃO, não por dia. Com
-- `maxRetries: 3` no job de resync (Google e Meta), um retry após o commit
-- da reconciliação contava a mesma ausência de novo, consumindo em 2
-- execuções a carência de 3 dias que protege a conta do cliente.
-- `last_missed_on` torna o incremento idempotente por dia: passa a guardar a
-- data (no fuso da CONTA, nunca do relógio do servidor) da última ausência já
-- somada em missed_syncs, para o incremento virar condicional a essa data ter
-- mudado. A leitura/gravação condicional é das Tasks 2 e 3 desta spec; esta
-- task só abre a coluna.
--
-- NULL = nunca teve ausência contada. É o estado de toda linha hoje, e é o
-- único valor que não faz a primeira execução pós-deploy pular a ausência
-- real do dia — um default de data faria toda conta parecer já contada.
--
-- Sem NOT NULL, sem default, sem backfill: DDL aditiva que não reescreve a
-- tabela nem tranca linhas existentes.
ALTER TABLE google_ads_accounts ADD COLUMN IF NOT EXISTS last_missed_on DATE;
ALTER TABLE meta_ad_accounts    ADD COLUMN IF NOT EXISTS last_missed_on DATE;

COMMENT ON COLUMN google_ads_accounts.last_missed_on IS
  'Data (fuso da conta) da última ausência já contada em missed_syncs. NULL = nunca contada.';
COMMENT ON COLUMN meta_ad_accounts.last_missed_on IS
  'Data (fuso da conta) da última ausência já contada em missed_syncs. NULL = nunca contada.';
