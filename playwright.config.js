const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({testDir:'tests/browser', use:{browserName:'chromium'}, reporter:'list'});
