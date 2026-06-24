/* eslint-disable no-undef */
/**
 * Shared Office.js named-range reader.
 *
 * Cache hit path  (preloadedItems != null):
 *   • Filters the pre-built list of { name, worksheetName } POJOs by prefix.
 *   • Opens one Excel.run, looks each item up by name, loads values — ONE sync.
 *
 * Cache miss path (preloadedItems == null):
 *   • Full enumeration: loads workbook + worksheet name lists (sync 1),
 *     then batches all matching range value loads (sync 2).
 *
 * @param {string[]} prefixes        Named-item prefix filters.
 * @param {Array<{name:string, worksheetName:string|null}>|null} preloadedItems
 *   Plain POJO cache built at mount time. Pass null to force a full reload.
 * @returns {Promise<Array>}  Array of { name, worksheet, address, rows, cols, values }.
 */
export async function readNamedRangesByPrefixes(prefixes, preloadedItems = null) {
  if (preloadedItems) {
    const relevant = preloadedItems.filter((item) =>
      prefixes.some((p) => item.name.startsWith(p))
    );
    console.log(`#sym:userDefined [${prefixes}]`, relevant.map((i) => i.name));
    console.log(`⏱ readNamedRangesByPrefixes [${prefixes}]: cache hit (${relevant.length} ranges)`);
    return await Excel.run(async (context) => {
      const t0 = performance.now();
      const pending = relevant.map(({ name, worksheetName }) => {
        const namedItem = worksheetName
          ? context.workbook.worksheets.getItem(worksheetName).names.getItem(name)
          : context.workbook.names.getItem(name);
        const range = namedItem.getRange();
        range.load("address,values,rowCount,columnCount,worksheet/name");
        return { name, range };
      });
      await context.sync();
      console.log(`⏱ readNamedRangesByPrefixes ranges load: ${(performance.now() - t0).toFixed(0)} ms (cache hit)`);
      return pending.map(({ name, range }) => ({
        name,
        worksheet: range.worksheet.name,
        address: range.address,
        rows: range.rowCount,
        cols: range.columnCount,
        values: range.values,
      }));
    });
  }

  // Cache miss: full load — enumerate names then batch-load range values (two syncs total)
  return await Excel.run(async (context) => {
    const overallStart = performance.now();
    const workbookNames = context.workbook.names;
    workbookNames.load("items/name,items/type");
    const worksheets = context.workbook.worksheets;
    worksheets.load("items/name,names/name,names/type");
    await context.sync();
    console.log(`⏱ readNamedRangesByPrefixes names load: ${(performance.now() - overallStart).toFixed(0)} ms (cache miss)`);

    let allNamedItems = [...workbookNames.items];
    worksheets.items.forEach((ws) => {
      if (ws.names) allNamedItems = allNamedItems.concat(ws.names.items);
    });

    const userDefined = allNamedItems.filter(
      (item) => item.type === Excel.NamedItemType.range && prefixes.some((p) => item.name.startsWith(p))
    );
    console.log(`#sym:userDefined [${prefixes}]`, userDefined.map((i) => i.name));

    const t1 = performance.now();
    const pending = userDefined.map((namedItem) => {
      const range = namedItem.getRange();
      range.load("address,values,rowCount,columnCount,worksheet/name");
      return { namedItem, range };
    });
    await context.sync();
    console.log(`⏱ readNamedRangesByPrefixes ranges load: ${(performance.now() - t1).toFixed(0)} ms`);
    console.log(`⏱ readNamedRangesByPrefixes total: ${(performance.now() - overallStart).toFixed(0)} ms`);

    return pending.map(({ namedItem, range }) => ({
      name: namedItem.name,
      worksheet: range.worksheet.name,
      address: range.address,
      rows: range.rowCount,
      cols: range.columnCount,
      values: range.values,
    }));
  });
}

/**
 * Build the named-item POJO cache for a given set of prefixes.
 * Called once on component mount inside an Excel.run.
 * Stores only { name, worksheetName } — never values.
 *
 * @param {string[]} prefixes
 * @returns {Promise<Array<{name:string, worksheetName:string|null}>>}
 */
export async function buildNamedItemCache(prefixes) {
  const t0 = performance.now();
  const namedRefs = [];
  await Excel.run(async (context) => {
    const workbookNames = context.workbook.names;
    workbookNames.load("items/name,items/type");
    const worksheets = context.workbook.worksheets;
    worksheets.load("items/name,names/name,names/type");
    await context.sync();

    workbookNames.items.forEach((item) => {
      if (item.type === Excel.NamedItemType.range && prefixes.some((p) => item.name.startsWith(p))) {
        namedRefs.push({ name: item.name, worksheetName: null });
      }
    });
    worksheets.items.forEach((ws) => {
      if (ws.names) {
        ws.names.items.forEach((item) => {
          if (item.type === Excel.NamedItemType.range && prefixes.some((p) => item.name.startsWith(p))) {
            namedRefs.push({ name: item.name, worksheetName: ws.name });
          }
        });
      }
    });
  });
  console.log(`⏱ buildNamedItemCache [${prefixes}]: ${(performance.now() - t0).toFixed(0)} ms (${namedRefs.length} refs cached)`);
  return namedRefs;
}

/**
 * Ensure a target worksheet exists by copying a template worksheet if needed.
 *
 * @param {Excel.RequestContext} context
 * @param {string} templateSheetName
 * @param {string} targetSheetName
 */
export async function ensureTemplateSheetPresent(context, templateSheetName, targetSheetName) {
  const sheets = context.workbook.worksheets;
  sheets.load("items/name");
  await context.sync();

  const targetExists = sheets.items.some((sheet) => sheet.name === targetSheetName);
  if (targetExists) {
    console.log(`${targetSheetName} sheet already exists`);
    return;
  }

  const templateExists = sheets.items.some((sheet) => sheet.name === templateSheetName);
  if (!templateExists) {
    throw new Error(
      `Template sheet '${templateSheetName}' not found. Please ensure it exists in your workbook.`
    );
  }

  const templateSheet = sheets.getItem(templateSheetName);
  const copiedSheet = templateSheet.copy(Excel.WorksheetPositionType.after, templateSheet);
  copiedSheet.set({ name: targetSheetName });
  await context.sync();
}
