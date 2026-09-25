// Restore the page-only design packing before any scene module reads DATA.design.
// The packer leaves data/city-design.json intact. Restore the object API before any viewer module reads it.
(function unpackPageDesign(design) {
  const collections = ['buildings', 'furniture', 'venues', 'trees', 'stages', 'routes', 'streets', 'bridges'];
  for (const name of collections) {
    const packed = design[name];
    if (!packed || !packed.s || !packed.r) continue;
    const one = packed.s.length === 1;
    const records = packed.r.map(row => {
      const schema = packed.s[one ? 0 : row[0]], offset = one ? 0 : 1, record = {};
      for (let k = 0; k < schema.length; k++) record[schema[k]] = row[k + offset];
      return record;
    });
    design[name] = name === 'buildings' ? Object.fromEntries(records.map((record, id) => [id, record])) : records;
  }
  for (const name of ['routes', 'streets', 'bridges']) {
    const dimension = name === 'bridges' ? 3 : 2;
    for (const record of design[name]) {
      const packed = record.points;
      if (!packed || typeof packed[0] !== 'number') continue;
      const scale = packed[0], codes = packed[1];
      if (!Number.isInteger(scale) || !Array.isArray(codes) || codes.length % dimension) {
        throw new Error('Invalid packed road coordinates');
      }
      const current = new Array(dimension).fill(0), points = [];
      for (let i = 0; i < codes.length; i += dimension) {
        const point = new Array(dimension);
        for (let k = 0; k < dimension; k++) {
          current[k] += codes[i + k]; point[k] = current[k] / scale;
        }
        points.push(point);
      }
      record.points = points;
    }
  }
})(DATA.design);
