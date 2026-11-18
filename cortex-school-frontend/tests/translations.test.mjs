import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { translate } from "../src/translation.mjs";
const fr = JSON.parse(
  readFileSync(new URL("../src/fr.json", import.meta.url), "utf8"),
);
const tr = (value) => translate(value, "fr", fr);
test("French translates core navigation, login, chat and form labels", () => {
  assert.equal(tr("School settings"), "Paramètres de l’école");
  assert.equal(tr("Sign in to your school"), "Se connecter à son école");
  assert.equal(tr("New chat"), "Nouvelle discussion");
  assert.equal(tr("First Name"), "Prénom");
  assert.equal(tr("Students"), "Élèves");
});
test("every business workflow has a French action label", () => {
  const routes = JSON.parse(
    readFileSync(new URL("../src/contracts.json", import.meta.url), "utf8"),
  );
  for (const e of routes) assert.ok(fr[e.title], e.title);
});
test("generated labels and counts translate without altering identifiers", () => {
  assert.equal(tr("Select Student Id"), "Choisir : Élève");
  assert.equal(tr("8 records shown"), "8 éléments affichés");
  assert.equal(tr("1 records shown"), "1 élément affiché");
  assert.equal(
    tr("Good to see you, Amira."),
    "Heureux de vous retrouver, Amira !",
  );
  assert.equal(
    tr(" Welcome new learners into your school community. "),
    " Accueillez de nouveaux élèves dans votre communauté. ",
  );
});
test("English and unrecognized record content remain unchanged", () => {
  assert.equal(translate("School settings", "en", fr), "School settings");
  assert.equal(tr("Amira Ben Ali"), "Amira Ben Ali");
  assert.equal(tr("student-123"), "student-123");
});

test("review queue messages translate while preserving names and identifiers", () => {
  assert.equal(tr("Acknowledgement overdue for 6A"), "Accusé de réception en retard pour 6A");
  assert.equal(tr("6B attendance is missing"), "Présence non transmise pour 6B");
  assert.equal(tr("Registration request for Yasmine Ben Ali"), "Demande d’inscription pour Yasmine Ben Ali");
  assert.equal(tr("Invitation for teacher@example.test"), "Invitation pour teacher@example.test");
  assert.equal(tr("4 guardian acknowledgements remain outstanding."), "4 accusés de réception en attente.");
});
