-- =====================================================================
-- test1.sql – date de test pentru „Clinică online de psihologie” (etapa 1)
--
-- Toate datele sunt FICTIVE: nume inventate, email-uri @example.com,
-- numere de document cu prefixul TEST (nu sunt coduri reale de parafă/atestat).
--
-- Situații ilustrate:
--   * o persoană cu două profesii (Ionescu: psihiatru + psihoterapeut)
--   * promovare cu istoric (Popa: „sub supervizare” înlocuit de „autonom”,
--     programările viitoare mutate pe documentul nou + notificări)
--   * document nou „în așteptare”, încă neverificat (Dumitrescu: primar)
--   * specialist care nu mai colaborează (Constantin: programări anulate
--     automat + notificări)
--   * pacienți minori fără cont, cu contact de urgență și email comun (frații Marin)
--   * ședințe finalizate, programate, anulate și o neprezentare
--
-- Datele ședințelor sunt RELATIVE la ziua rulării (ex: „peste 7 zile”),
-- ca scriptul să rămână realist oricând este rulat.
--
-- Scriptul poate fi rulat de mai multe ori fără să dubleze datele:
--   * ON CONFLICT DO NOTHING -> pentru coloanele UNIQUE
--   * WHERE NOT EXISTS       -> pentru tabelele fără UNIQUE
--     (ședințele sunt identificate după link-ul întâlnirii, unic în test)
--
-- Conturile de login (Utilizator) NU se creează aici: parolele trebuie
-- criptate de Django. Creează-le din panoul de administrare, dacă e nevoie.
-- Dacă există un superuser, el apare ca persoana care a verificat /
-- dezactivat documentele.
--
-- Rulare:
--   * consola Neon -> SQL Editor -> lipești tot scriptul -> Run
--   * sau: python manage.py dbshell, apoi  \encoding UTF8  și  \i test1.sql
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. Profesii
-- ---------------------------------------------------------------------
INSERT INTO clinica_profesie (nume, organism_emitent, poate_prescrie, poate_diagnostica, grade_ierarhice) VALUES
    ('psihiatru',          'Colegiul Medicilor din România',    true,  true,  true),
    ('psihoterapeut',      'Colegiul Psihologilor din România', false, false, true),
    ('psiholog clinician', 'Colegiul Psihologilor din România', false, false, true)
ON CONFLICT (nume) DO NOTHING;

-- ---------------------------------------------------------------------
-- 2. Grade profesionale (catalog: profesie + grad + poziția în ierarhie)
--    „specialist” apare la două profesii: permis, numele e unic doar
--    în cadrul profesiei.
-- ---------------------------------------------------------------------
INSERT INTO clinica_gradprofesional (profesie_id, nume, ordine, poate_superviza)
SELECT p.id, v.nume, v.ordine, v.superviza
FROM (VALUES
        ('psihiatru',          'rezident',        1, false),
        ('psihiatru',          'specialist',      2, false),
        ('psihiatru',          'primar',          3, true),
        ('psihoterapeut',      'în formare',      1, false),
        ('psihoterapeut',      'sub supervizare', 2, false),
        ('psihoterapeut',      'autonom',         3, true),
        ('psiholog clinician', 'practicant',      1, false),
        ('psiholog clinician', 'specialist',      2, false),
        ('psiholog clinician', 'principal',       3, true)
     ) AS v(profesie, nume, ordine, superviza)
JOIN clinica_profesie p ON p.nume = v.profesie
ON CONFLICT (profesie_id, nume) DO NOTHING;

-- ---------------------------------------------------------------------
-- 3. Specialiști
-- ---------------------------------------------------------------------
INSERT INTO clinica_specialist
    (nume, prenume, telefon, data_inregistrare, email, descriere, accepta_pacienti_noi)
SELECT v.nume, v.prenume, v.telefon, now() - make_interval(days => v.inregistrat_acum_zile),
       v.email, v.descriere, v.accepta
FROM (VALUES
        ('Ionescu',    'Maria',  '0700100001', 1100, 'maria.ionescu@example.com',
         'Medic psihiatru și psihoterapeut cognitiv-comportamental.', true),
        ('Popa',       'Andrei', '0700100002',  900, 'andrei.popa@example.com',
         'Psihoterapeut de familie și cuplu, abordare sistemică.', true),
        ('Stan',       'Elena',  '0700100003',  800, 'elena.stan@example.com',
         'Psiholog clinician. Psihoterapeut cognitiv-comportamental în supervizare.', true),
        ('Dumitrescu', 'Radu',   '0700100004',  600, 'radu.dumitrescu@example.com',
         'Medic psihiatru, tulburări de anxietate și de somn.', true),
        ('Constantin', 'Ana',    '',           1000, 'ana.constantin@example.com',
         'Nu mai colaborează cu clinica.', false)
     ) AS v(nume, prenume, telefon, inregistrat_acum_zile, email, descriere, accepta)
ON CONFLICT (email) DO NOTHING;

-- ---------------------------------------------------------------------
-- 4. Calificări (documente)
--    Reguli respectate de date:
--      * cel mult un document ACTIV pe specialist + profesie + domeniu
--      * numărul documentului e unic în cadrul organismului emitent
--      * activă => fără motiv de dezactivare; dezactivată => motiv + dată
--      * verificată => are data verificării
-- ---------------------------------------------------------------------
INSERT INTO clinica_calificare
    (specialist_id, grad_id, domeniu, nr_document, data_obtinere, data_expirare, activa, tarif_sedinta,
     verificata, verificata_de_id, verificata_la,
     motiv_dezactivare, dezactivata_de_id, dezactivata_la)
SELECT s.id, g.id, v.domeniu, v.nr, v.obtinere::date, v.expirare::date, v.activa, v.tarif,
       v.verificata,
       CASE WHEN v.verificata THEN adm.id END,
       CASE WHEN v.verificata THEN now() - make_interval(days => v.verificat_acum_zile) END,
       v.motiv,
       CASE WHEN v.motiv <> '' THEN adm.id END,
       CASE WHEN v.motiv <> '' THEN now() - make_interval(days => v.dezactivat_acum_zile) END
FROM (VALUES
        -- Ionescu: două profesii, ambele active
        ('maria.ionescu@example.com',   'psihiatru',          'primar',          '',
         'P-TEST-0001',  '2012-06-01', NULL,         true,  300.00, true,  900, '',                    NULL),
        ('maria.ionescu@example.com',   'psihoterapeut',      'autonom',         'cognitiv-comportamentală',
         'AT-TEST-0001', '2016-03-15', NULL,         true,  250.00, true,  900, '',                    NULL),
        -- Popa: documentul vechi, înlocuit la promovare...
        ('andrei.popa@example.com',     'psihoterapeut',      'sub supervizare', 'sistemică',
         'AT-TEST-0002', '2019-09-01', NULL,         false, 180.00, true,  700, 'promovare',           20),
        -- ...și documentul nou, activ
        ('andrei.popa@example.com',     'psihoterapeut',      'autonom',         'sistemică',
         'AT-TEST-0003', '2026-10-10', NULL,         true,  230.00, true,   25, '',                    NULL),
        -- Stan: psiholog clinician + psihoterapeut în supervizare (document cu expirare)
        ('elena.stan@example.com',      'psiholog clinician', 'principal',       '',
         'CP-TEST-0001', '2014-02-01', NULL,         true,  220.00, true,  800, '',                    NULL),
        ('elena.stan@example.com',      'psihoterapeut',      'sub supervizare', 'cognitiv-comportamentală',
         'AT-TEST-0004', '2024-05-01', '2027-05-01', true,  150.00, true,  500, '',                    NULL),
        -- Dumitrescu: documentul activ + unul nou „în așteptare” (neverificat, inactiv)
        ('radu.dumitrescu@example.com', 'psihiatru',          'specialist',      '',
         'P-TEST-0002',  '2018-10-01', NULL,         true,  250.00, true,  600, '',                    NULL),
        ('radu.dumitrescu@example.com', 'psihiatru',          'primar',          '',
         'P-TEST-0003',  '2026-10-20', NULL,         false, 300.00, false, NULL, '',                   NULL),
        -- Constantin: dezactivată, nu mai colaborează cu clinica
        ('ana.constantin@example.com',  'psihoterapeut',      'autonom',         'psihodramă',
         'AT-TEST-0005', '2015-01-10', NULL,         false, 240.00, true, 1000, 'incetare_colaborare',  5)
     ) AS v(email, profesie, grad, domeniu, nr, obtinere, expirare, activa, tarif,
            verificata, verificat_acum_zile, motiv, dezactivat_acum_zile)
JOIN clinica_specialist      s ON s.email = v.email
JOIN clinica_profesie        p ON p.nume = v.profesie
JOIN clinica_gradprofesional g ON g.profesie_id = p.id AND g.nume = v.grad
-- primul superuser (dacă există) apare ca cel care a verificat / dezactivat
LEFT JOIN (SELECT id FROM clinica_utilizator WHERE is_superuser ORDER BY id LIMIT 1) adm ON true
WHERE NOT EXISTS (
    SELECT 1
    FROM clinica_calificare x
    JOIN clinica_gradprofesional gx ON gx.id = x.grad_id
    JOIN clinica_profesie        px ON px.id = gx.profesie_id
    WHERE x.nr_document = v.nr
      AND px.organism_emitent = p.organism_emitent
);

-- ---------------------------------------------------------------------
-- 5. Pacienți
--    Frații Marin: minori, fără telefon propriu, cu același email (al
--    părintelui) și cu mama ca persoană de contact.
-- ---------------------------------------------------------------------
INSERT INTO clinica_pacient
    (nume, prenume, telefon, data_inregistrare, data_nasterii, sex, email,
     contact_urgenta_nume, contact_urgenta_telefon, data_consimtamant)
SELECT v.nume, v.prenume, v.telefon, now() - make_interval(days => v.inregistrat_acum_zile),
       v.nascut::date, v.sex, v.email, v.contact_nume, v.contact_telefon,
       CASE WHEN v.consimtamant THEN now() - make_interval(days => v.inregistrat_acum_zile) END
FROM (VALUES
        ('Popescu',   'Ion',      '0711000001', 120, '1985-03-14', 'M', 'ion.popescu@example.com',
         'Popescu Elena',       '0711000101', true),
        ('Georgescu', 'Ana',      '0711000002',  90, '1992-07-22', 'F', 'ana.georgescu@example.com',
         '',                    '',           true),
        ('Marin',     'Vlad',     '',            60, '2013-11-05', 'M', 'familia.marin@example.com',
         'Marin Carmen (mamă)', '0711000103', true),
        ('Marin',     'Irina',    '',            60, '2016-02-19', 'F', 'familia.marin@example.com',
         'Marin Carmen (mamă)', '0711000103', true),
        ('Tudor',     'Ioana',    '0711000005',  45, '1978-01-30', 'F', 'ioana.tudor@example.com',
         '',                    '',           true),
        ('Radu',      'Mihai',    '0711000006', 200, '1964-09-12', 'M', 'mihai.radu@example.com',
         'Radu Maria',          '0711000106', true),
        ('Enache',    'Cristina', '0711000007',  30, '2001-05-18', 'F', 'cristina.enache@example.com',
         '',                    '',           true),
        -- pacient nou: fără email și încă fără consimțământ GDPR
        ('Nistor',    'Alex',     '0711000008',  10, '1999-04-27', 'A', '',
         '',                    '',           false)
     ) AS v(nume, prenume, telefon, inregistrat_acum_zile, nascut, sex, email,
            contact_nume, contact_telefon, consimtamant)
WHERE NOT EXISTS (
    SELECT 1 FROM clinica_pacient x
    WHERE x.nume = v.nume AND x.prenume = v.prenume AND x.data_nasterii = v.nascut::date
);

-- ---------------------------------------------------------------------
-- 6. Ședințe
--    zile < 0 = în trecut, zile > 0 = în viitor (față de ziua rulării).
--    Ședința indică un DOCUMENT (calificare): se vede cine a ținut-o și în ce rol.
--    Prețul se copiază din tariful documentului.
--    Ședințele programate în viitor folosesc doar documente active,
--    verificate și neexpirate la data ședinței.
-- ---------------------------------------------------------------------
INSERT INTO clinica_sedinta
    (pacient_id, calificare_id, data_ora, durata_minute, status, link_intalnire, pret,
     note_confidentiale, motiv_anulare, anulata_la, creata_la)
SELECT p.id, c.id, d.data_ora, v.durata, v.status, v.link, c.tarif_sedinta,
       v.note, v.motiv_anulare,
       CASE WHEN v.status = 'anulata' THEN now() - make_interval(days => v.anulat_acum_zile) END,
       LEAST(now(), d.data_ora - interval '10 days')
FROM (VALUES
        -- Ionescu, ca psihiatru
        ('https://meet.example.com/test-01', 'Popescu',   'Ion',      'P-TEST-0001',  -60, '10:00', 30, 'finalizata',
         'Evaluare inițială: simptome depresive moderate.', '', NULL),
        ('https://meet.example.com/test-02', 'Popescu',   'Ion',      'P-TEST-0001',  -30, '10:00', 30, 'finalizata',
         'Control. Evoluție favorabilă.', '', NULL),
        ('https://meet.example.com/test-03', 'Popescu',   'Ion',      'P-TEST-0001',    7, '10:00', 30, 'programata',
         '', '', NULL),
        -- Ionescu, ca psihoterapeut
        ('https://meet.example.com/test-04', 'Georgescu', 'Ana',      'AT-TEST-0001', -21, '17:00', 50, 'finalizata',
         '', '', NULL),
        ('https://meet.example.com/test-05', 'Georgescu', 'Ana',      'AT-TEST-0001', -14, '17:00', 50, 'neprezentare',
         'Pacienta nu s-a conectat.', '', NULL),
        ('https://meet.example.com/test-06', 'Georgescu', 'Ana',      'AT-TEST-0001',  -7, '17:00', 50, 'finalizata',
         '', '', NULL),
        ('https://meet.example.com/test-07', 'Georgescu', 'Ana',      'AT-TEST-0001',   7, '17:00', 50, 'programata',
         '', '', NULL),
        -- Popa: ședințe ținute înainte de promovare, pe documentul vechi (istoric)
        ('https://meet.example.com/test-08', 'Radu',      'Mihai',    'AT-TEST-0002', -40, '18:00', 50, 'finalizata',
         '', '', NULL),
        ('https://meet.example.com/test-09', 'Radu',      'Mihai',    'AT-TEST-0002', -26, '18:00', 50, 'finalizata',
         '', '', NULL),
        -- Popa: programări mutate pe documentul nou la promovare
        ('https://meet.example.com/test-10', 'Radu',      'Mihai',    'AT-TEST-0003',   2, '18:00', 50, 'programata',
         '', '', NULL),
        ('https://meet.example.com/test-11', 'Tudor',     'Ioana',    'AT-TEST-0003',   9, '16:00', 50, 'programata',
         '', '', NULL),
        -- Stan, ca psiholog clinician
        ('https://meet.example.com/test-12', 'Marin',     'Vlad',     'CP-TEST-0001', -10, '14:00', 50, 'finalizata',
         'Evaluare psihologică.', '', NULL),
        ('https://meet.example.com/test-13', 'Marin',     'Irina',    'CP-TEST-0001',   4, '14:00', 50, 'programata',
         '', '', NULL),
        -- Stan, ca psihoterapeut (inclusiv o anulare cerută de pacient)
        ('https://meet.example.com/test-14', 'Enache',    'Cristina', 'AT-TEST-0004',  -5, '19:00', 50, 'finalizata',
         '', '', NULL),
        ('https://meet.example.com/test-15', 'Enache',    'Cristina', 'AT-TEST-0004',   3, '19:00', 50, 'anulata',
         '', 'Pacienta a cerut reprogramarea.', 1),
        ('https://meet.example.com/test-16', 'Enache',    'Cristina', 'AT-TEST-0004',  10, '19:00', 50, 'programata',
         '', '', NULL),
        -- Dumitrescu, ca psihiatru specialist
        ('https://meet.example.com/test-17', 'Tudor',     'Ioana',    'P-TEST-0002',   -3, '11:00', 30, 'finalizata',
         '', '', NULL),
        ('https://meet.example.com/test-18', 'Nistor',    'Alex',     'P-TEST-0002',    5, '11:30', 30, 'programata',
         '', '', NULL),
        -- Constantin: ședință din trecut + programări anulate la dezactivare
        ('https://meet.example.com/test-19', 'Tudor',     'Ioana',    'AT-TEST-0005', -20, '15:00', 50, 'finalizata',
         '', '', NULL),
        ('https://meet.example.com/test-20', 'Tudor',     'Ioana',    'AT-TEST-0005',   6, '15:00', 50, 'anulata',
         '', 'Specialistul nu mai este disponibil.', 5),
        ('https://meet.example.com/test-21', 'Marin',     'Vlad',     'AT-TEST-0005',   8, '15:00', 50, 'anulata',
         '', 'Specialistul nu mai este disponibil.', 5)
     ) AS v(link, nume, prenume, nr, zile, ora, durata, status, note, motiv_anulare, anulat_acum_zile)
JOIN clinica_pacient    p ON p.nume = v.nume AND p.prenume = v.prenume
JOIN clinica_calificare c ON c.nr_document = v.nr
-- data și ora, în fusul orar al clinicii
CROSS JOIN LATERAL (
    SELECT ((CURRENT_DATE + v.zile) + v.ora::time) AT TIME ZONE 'Europe/Bucharest' AS data_ora
) d
WHERE NOT EXISTS (SELECT 1 FROM clinica_sedinta x WHERE x.link_intalnire = v.link);

-- ---------------------------------------------------------------------
-- 7. Notificări
--    Mesajele se compun din datele reale ale ședinței (dată, specialist, grad).
--    citita_acum_zile = NULL -> necitită / netransmisă încă.
-- ---------------------------------------------------------------------
INSERT INTO clinica_notificare (pacient_id, sedinta_id, tip, mesaj, creata_la, citita_la)
SELECT s.pacient_id, s.id, v.tip,
       format(v.sablon,
              to_char(s.data_ora AT TIME ZONE 'Europe/Bucharest', 'DD.MM.YYYY, "ora" HH24:MI'),
              sp.nume || ' ' || sp.prenume,
              pr.nume || ' ' || g.nume),
       now() - make_interval(days => v.creata_acum_zile),
       CASE WHEN v.citita_acum_zile IS NOT NULL THEN now() - make_interval(days => v.citita_acum_zile) END
FROM (VALUES
        ('https://meet.example.com/test-10', 'mutare',  20, 19,
         'Ședința din %1$s rămâne programată. %2$s are acum gradul de %3$s.'),
        ('https://meet.example.com/test-11', 'mutare',  20, NULL,
         'Ședința din %1$s rămâne programată. %2$s are acum gradul de %3$s.'),
        ('https://meet.example.com/test-20', 'anulare',  5, 4,
         'Ședința din %1$s cu %2$s a fost anulată, deoarece specialistul nu mai este disponibil. '
         'Vă rugăm să programați o nouă ședință.'),
        ('https://meet.example.com/test-21', 'anulare',  5, NULL,
         'Ședința din %1$s cu %2$s a fost anulată, deoarece specialistul nu mai este disponibil. '
         'Vă rugăm să programați o nouă ședință.')
     ) AS v(link, tip, creata_acum_zile, citita_acum_zile, sablon)
JOIN clinica_sedinta         s  ON s.link_intalnire = v.link
JOIN clinica_calificare      c  ON c.id = s.calificare_id
JOIN clinica_specialist      sp ON sp.id = c.specialist_id
JOIN clinica_gradprofesional g  ON g.id = c.grad_id
JOIN clinica_profesie        pr ON pr.id = g.profesie_id
WHERE NOT EXISTS (
    SELECT 1 FROM clinica_notificare x WHERE x.sedinta_id = s.id AND x.tip = v.tip
);

COMMIT;

-- ---------------------------------------------------------------------
-- Verificare: câte rânduri are fiecare tabel
-- ---------------------------------------------------------------------
SELECT 'profesii'               AS tabel, COUNT(*) AS randuri FROM clinica_profesie
UNION ALL SELECT 'grade profesionale', COUNT(*) FROM clinica_gradprofesional
UNION ALL SELECT 'specialisti',        COUNT(*) FROM clinica_specialist
UNION ALL SELECT 'calificari',         COUNT(*) FROM clinica_calificare
UNION ALL SELECT 'pacienti',           COUNT(*) FROM clinica_pacient
UNION ALL SELECT 'sedinte',            COUNT(*) FROM clinica_sedinta
UNION ALL SELECT 'notificari',         COUNT(*) FROM clinica_notificare;


-- =====================================================================
-- Interogări utile pentru prezentare (scoate „--” din față ca să le rulezi)
-- =====================================================================

-- 1. Ședințele, cu rolul în care le-a ținut fiecare specialist
-- SELECT s.data_ora AT TIME ZONE 'Europe/Bucharest' AS data_ora,
--        p.nume || ' ' || p.prenume   AS pacient,
--        sp.nume || ' ' || sp.prenume AS specialist,
--        pr.nume || ' ' || g.nume     AS rol,
--        s.status, s.pret
-- FROM clinica_sedinta s
-- JOIN clinica_pacient         p  ON p.id  = s.pacient_id
-- JOIN clinica_calificare      c  ON c.id  = s.calificare_id
-- JOIN clinica_specialist      sp ON sp.id = c.specialist_id
-- JOIN clinica_gradprofesional g  ON g.id  = c.grad_id
-- JOIN clinica_profesie        pr ON pr.id = g.profesie_id
-- ORDER BY s.data_ora;

-- 2. Specialiștii cu mai multe profesii active
-- SELECT sp.nume, sp.prenume, string_agg(pr.nume || ' ' || g.nume, ', ') AS calificari_active
-- FROM clinica_calificare c
-- JOIN clinica_specialist      sp ON sp.id = c.specialist_id
-- JOIN clinica_gradprofesional g  ON g.id  = c.grad_id
-- JOIN clinica_profesie        pr ON pr.id = g.profesie_id
-- WHERE c.activa
-- GROUP BY sp.id, sp.nume, sp.prenume
-- HAVING COUNT(DISTINCT pr.id) > 1;

-- 3. Istoricul documentelor fiecărui specialist (active, în așteptare, dezactivate)
-- SELECT sp.nume, sp.prenume, pr.nume AS profesie, g.nume AS grad, c.domeniu, c.nr_document,
--        CASE WHEN c.activa THEN 'activă'
--             WHEN c.motiv_dezactivare = '' THEN 'în așteptare'
--             ELSE 'dezactivată: ' || c.motiv_dezactivare END AS stare
-- FROM clinica_calificare c
-- JOIN clinica_specialist      sp ON sp.id = c.specialist_id
-- JOIN clinica_gradprofesional g  ON g.id  = c.grad_id
-- JOIN clinica_profesie        pr ON pr.id = g.profesie_id
-- ORDER BY sp.nume, pr.nume, g.ordine;

-- 4. Pacienți fără cont care au notificări necitite (de contactat telefonic)
-- SELECT p.nume, p.prenume,
--        COALESCE(NULLIF(p.telefon, ''), p.contact_urgenta_telefon) AS telefon,
--        n.mesaj
-- FROM clinica_notificare n
-- JOIN clinica_pacient p ON p.id = n.pacient_id
-- WHERE n.citita_la IS NULL AND p.utilizator_id IS NULL;
