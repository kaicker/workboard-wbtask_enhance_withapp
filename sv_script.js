var SV = {
  shift: '',
  svName: '',
  items: [],
  uploaded: false,
  user: '',
  userFullName: ''
};

function svInit() {
  SV.user = frappe.session.user;
  SV.userFullName = frappe.session.user_fullname || SV.user;
  document.getElementById('sv-user-display').textContent = SV.userFullName;
  document.getElementById('sv-entry-by').value = SV.userFullName || SV.user || '';

  var days = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
  var months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  var d = new Date();
  document.getElementById('sv-date-display').textContent = days[d.getDay()] + ', ' + d.getDate() + ' ' + months[d.getMonth()] + ' ' + d.getFullYear();

  svLoadEmployees();
  svLoadLanding();
}

function svLoadEmployees() {
  frappe.call({
    method: 'frappe.client.get_list',
    args: {
      doctype: 'Employee',
      filters: { status: 'Active' },
      fields: ['employee_name'],
      limit_page_length: 0,
      order_by: 'employee_name asc'
    },
    callback: function(r) {
      var dl = document.getElementById('sv-employee-list');
      if (!dl || !r.message) return;
      dl.innerHTML = '';
      var seen = {};
      r.message.forEach(function(e) {
        var n = (e.employee_name || '').trim();
        if (!n || seen[n.toLowerCase()]) return;
        seen[n.toLowerCase()] = true;
        var opt = document.createElement('option');
        opt.value = n;
        dl.appendChild(opt);
      });
    }
  });
}

function svLoadLanding() {
  var body = document.getElementById('sv-shifts-body');
  body.innerHTML = '<div class="sv-loading">Loading...</div>';

  frappe.call({
    method: 'sv_today_status',
    callback: function(r) {
      var data = r.message || {};
      var am = data.am;
      var pm = data.pm;
      var html = '';

      // AM shift
      var amStatus = am ? am.status : 'Not started';
      var amPill = 'sv-pill-amber';
      var amLabel = 'Pending';
      var amBtn = '';
      if (am && am.status === 'Submitted') {
        amPill = 'sv-pill-green'; amLabel = 'Submitted';
        amBtn = '<button class="sv-btn" style="width:100%;margin-top:10px" disabled>Completed</button>';
      } else if (am && (am.status === 'Counting' || am.status === 'Counted')) {
        amPill = 'sv-pill-blue'; amLabel = am.status;
        amBtn = '<button class="sv-btn sv-btn-primary" style="width:100%;margin-top:10px" onclick="svStartShift(\'AM\')">Continue</button>';
      } else {
        amBtn = '<button class="sv-btn sv-btn-primary" style="width:100%;margin-top:10px" onclick="svStartShift(\'AM\')">Start counting</button>';
      }

      html += '<div class="sv-shift-card' + (amStatus !== 'Submitted' ? ' active' : '') + '">';
      html += '<div class="shift-top"><span class="shift-name">AM shift</span><span class="sv-pill ' + amPill + '">' + amLabel + '</span></div>';
      html += '<div class="shift-detail">ERP snapshot at 11:00 AM &middot; 39 categories</div>';
      html += amBtn + '</div>';

      // PM shift
      var now = new Date();
      var pmAvailable = now.getHours() >= 18 || (now.getHours() === 17 && now.getMinutes() >= 30);
      var pmStatus = pm ? pm.status : 'Not started';
      var pmPill = 'sv-pill-blue';
      var pmLabel = '6:30 PM';
      var pmBtn = '';

      if (pm && pm.status === 'Submitted') {
        pmPill = 'sv-pill-green'; pmLabel = 'Submitted';
        pmBtn = '<button class="sv-btn" style="width:100%;margin-top:10px" disabled>Completed</button>';
      } else if (pm && (pm.status === 'Counting' || pm.status === 'Counted')) {
        pmPill = 'sv-pill-blue'; pmLabel = pm.status;
        pmBtn = '<button class="sv-btn sv-btn-primary" style="width:100%;margin-top:10px" onclick="svStartShift(\'PM\')">Continue</button>';
      } else if (pmAvailable) {
        pmPill = 'sv-pill-amber'; pmLabel = 'Pending';
        pmBtn = '<button class="sv-btn sv-btn-primary" style="width:100%;margin-top:10px" onclick="svStartShift(\'PM\')">Start counting</button>';
      }

      html += '<div class="sv-shift-card' + (!pmAvailable && !pm ? ' disabled' : '') + '">';
      html += '<div class="shift-top"><span class="shift-name">PM shift</span><span class="sv-pill ' + pmPill + '">' + pmLabel + '</span></div>';
      html += '<div class="shift-detail">' + (pmAvailable || pm ? '39 categories' : 'Available at 6:30 PM') + '</div>';
      html += pmBtn + '</div>';

      body.innerHTML = html;
    }
  });
}

function svStartShift(sh) {
  SV.shift = sh;
  // Create or fetch the record with ERP snapshot
  frappe.call({
    method: 'sv_create_snapshot',
    args: { shift: sh },
    freeze: true,
    freeze_message: 'Loading ERP data...',
    callback: function(r) {
      var data = r.message;
      SV.svName = data.name;
      SV.items = data.items;

      // Restore upload state if the record already has a sheet attached.
      // Server may return data.sheet_image OR data.sheet_uploaded.
      // Fallback: if the record has progressed past 'Not started' it must have had a sheet
      // (since this rule is enforced at upload-time going forward).
      SV.uploaded = !!(data.sheet_image || data.sheet_uploaded);

      // If already counted or beyond, restore data and go to right state
      if (data.status === 'Counted') {
        if (data.counted_by_1) document.getElementById('sv-counted-by-1').value = data.counted_by_1;
        if (data.counted_by_2) document.getElementById('sv-counted-by-2').value = data.counted_by_2;
        if (data.remarks) document.getElementById('sv-setup-remarks').value = data.remarks;
        svGoState('2');
      } else if (data.status === 'Counting') {
        if (data.counted_by_1) document.getElementById('sv-counted-by-1').value = data.counted_by_1;
        if (data.counted_by_2) document.getElementById('sv-counted-by-2').value = data.counted_by_2;
        if (data.remarks) document.getElementById('sv-setup-remarks').value = data.remarks;
        svGoState('1');
      } else {
        svGoState('0b');
      }
    }
  });
}

function svTryProceedToEntry() {
  if (!SV.uploaded) {
    svShowToast('Please upload the paper sheet to continue');
    var z = document.getElementById('sv-upload-zone');
    if (z) {
      z.style.borderColor = '#c0392b';
      z.style.background = '#fdecea';
      setTimeout(function(){ z.style.borderColor = ''; z.style.background = ''; }, 1400);
      z.scrollIntoView({behavior:'smooth', block:'center'});
    }
    return;
  }
  svGoState('1');
}

function svGoState(id) {
  document.querySelectorAll('.sv-state').forEach(function(e){ e.classList.remove('active'); });
  document.getElementById('sv-state-' + id).classList.add('active');
  window.scrollTo(0, 0);

  if (id === '0') {
    svLoadLanding();
  }

  if (id === '0b') {
    document.getElementById('sv-setup-title').textContent = SV.shift + ' \u2014 Setup';
    document.getElementById('sv-setup-meta').textContent = frappe.datetime.nowdate() + ' \u00b7 ' + SV.shift;
    var z = document.getElementById('sv-upload-zone');
    if (z && SV.uploaded) {
      z.classList.add('sv-upload-done');
      z.innerHTML = '<p>Sheet uploaded</p><p class="hint">Tap to replace</p>';
    }
  }

  if (id === '1') {
    var n1 = document.getElementById('sv-counted-by-1').value || '\u2014';
    var n2 = document.getElementById('sv-counted-by-2').value;
    document.getElementById('sv-entry-meta').textContent = 'Counted by: ' + n1 + (n2 ? ', ' + n2 : '');
    document.getElementById('sv-entry-title').textContent = SV.shift + ' \u2014 Enter counts';
    document.getElementById('sv-sheet-status').style.display = SV.uploaded ? 'flex' : 'none';
    svRenderGrid();
  }

  if (id === '2') {
    document.getElementById('sv-recon-title').textContent = SV.shift + ' \u2014 Differences';
    svRenderRecon();
  }

  if (id === 'done') {
    document.getElementById('sv-done-msg').textContent = SV.shift + ' verification locked \u00b7 ' + frappe.datetime.nowdate();
  }
}

function svRenderGrid() {
  var g = document.getElementById('sv-entry-grid');
  g.innerHTML = '';
  for (var i = 0; i < SV.items.length; i++) {
    var item = SV.items[i];
    var r = document.createElement('div');
    r.className = 'sv-grid-row';
    r.innerHTML = '<span class="sv-cat-name">' + item.category + '</span>' +
      '<input class="sv-num-input" type="number" inputmode="numeric" pattern="[0-9]*" placeholder="-" data-i="' + i + '" data-f="main_safe" value="' + (item.main_safe || '') + '" oninput="svUpdateEntry(this)">' +
      '<input class="sv-num-input" type="number" inputmode="numeric" pattern="[0-9]*" placeholder="-" data-i="' + i + '" data-f="loose_tray" value="' + (item.loose_tray || '') + '" oninput="svUpdateEntry(this)">' +
      '<input class="sv-num-input" type="number" inputmode="numeric" pattern="[0-9]*" placeholder="-" data-i="' + i + '" data-f="outside_display" value="' + (item.outside_display || '') + '" oninput="svUpdateEntry(this)">';
    g.appendChild(r);
  }
  svUpdateFillCount();
}

function svUpdateEntry(el) {
  var i = parseInt(el.dataset.i);
  var f = el.dataset.f;
  SV.items[i][f] = el.value === '' ? 0 : parseInt(el.value);
  svUpdateFillCount();
}

function svUpdateFillCount() {
  var n = 0;
  for (var i = 0; i < SV.items.length; i++) {
    var item = SV.items[i];
    if ((item.main_safe || 0) > 0 || (item.loose_tray || 0) > 0 || (item.outside_display || 0) > 0) n++;
  }
  document.getElementById('sv-entry-count').textContent = n + ' / ' + SV.items.length + ' filled';
}

function svBuildCountsPayload() {
  var counts = [];
  for (var i = 0; i < SV.items.length; i++) {
    var item = SV.items[i];
    counts.push({
      category: item.category,
      s: item.main_safe || 0,
      t: item.loose_tray || 0,
      o: item.outside_display || 0,
      rem: item.remark || ''
    });
  }
  return counts;
}

function svSaveDraft() {
  var counts = svBuildCountsPayload();
  frappe.call({
    method: 'sv_save_counts',
    args: {
      sv_name: SV.svName,
      counts: JSON.stringify(counts),
      counted_by_1: document.getElementById('sv-counted-by-1').value || '',
      counted_by_2: document.getElementById('sv-counted-by-2').value || '',
      remarks: document.getElementById('sv-setup-remarks').value || '',
      action: 'draft'
    },
    freeze: true,
    freeze_message: 'Saving draft...',
    callback: function(r) {
      SV.items = r.message.items;
      svShowToast('Draft saved');
    }
  });
}

function svSaveCounts() {
  var empty = 0;
  for (var i = 0; i < SV.items.length; i++) {
    var item = SV.items[i];
    if (!(item.main_safe || 0) && !(item.loose_tray || 0) && !(item.outside_display || 0)) empty++;
  }
  if (empty > 10 && !confirm(empty + ' categories have no counts. Save anyway?')) return;

  var counts = svBuildCountsPayload();
  frappe.call({
    method: 'sv_save_counts',
    args: {
      sv_name: SV.svName,
      counts: JSON.stringify(counts),
      counted_by_1: document.getElementById('sv-counted-by-1').value || '',
      counted_by_2: document.getElementById('sv-counted-by-2').value || '',
      remarks: document.getElementById('sv-setup-remarks').value || '',
      action: 'save'
    },
    freeze: true,
    freeze_message: 'Saving counts...',
    callback: function(r) {
      SV.items = r.message.items;
      svGoState('2');
    }
  });
}

function svRenderRecon() {
  var ok = 0, mm = [];
  for (var i = 0; i < SV.items.length; i++) {
    var item = SV.items[i];
    var pt = (item.main_safe || 0) + (item.loose_tray || 0) + (item.outside_display || 0);
    var diff = (item.physical_total || pt) - (item.erp_count || 0);
    if (diff === 0) {
      ok++;
    } else {
      mm.push({ idx: i, cat: item.category, physical: item.physical_total || pt, erp: item.erp_count || 0, diff: diff, s: item.main_safe || 0, t: item.loose_tray || 0, o: item.outside_display || 0, remark: item.remark || '' });
    }
  }

  document.getElementById('sv-recon-pills').innerHTML = '<span class="sv-pill sv-pill-green">' + ok + ' matched</span><span class="sv-pill sv-pill-red">' + mm.length + ' difference' + (mm.length !== 1 ? 's' : '') + '</span>';

  var b = document.getElementById('sv-recon-body');
  if (mm.length === 0) {
    b.innerHTML = '<div class="sv-all-good"><div class="icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></div><h3>All categories match</h3><p>No differences to reconcile</p></div>';
    return;
  }

  b.innerHTML = '<p style="font-size:11px;color:var(--text-light);margin-bottom:10px">Save anytime \u2014 come back later to finish remarks</p>';
  for (var j = 0; j < mm.length; j++) {
    var m = mm[j];
    var sign = m.diff > 0 ? '+' : '';
    var c = document.createElement('div');
    c.className = 'sv-recon-card';
    c.innerHTML = '<div class="top-row"><span class="cat">' + m.cat + '</span><span class="diff">' + sign + m.diff + '</span></div>' +
      '<div class="detail">Count ' + m.physical + ' vs ERP ' + m.erp + ' \u00b7 Safe ' + m.s + ' \u00b7 Tray ' + m.t + ' \u00b7 Out ' + m.o + '</div>' +
      '<textarea placeholder="Reason for difference..." data-idx="' + m.idx + '" oninput="svUpdateRemark(this)">' + (m.remark || '') + '</textarea>';
    b.appendChild(c);
  }
}

function svUpdateRemark(el) {
  var idx = parseInt(el.dataset.idx);
  SV.items[idx].remark = el.value;
}

function svSaveRemarks() {
  var counts = svBuildCountsPayload();
  // Update remarks into counts
  for (var i = 0; i < SV.items.length; i++) {
    counts[i].rem = SV.items[i].remark || '';
  }
  frappe.call({
    method: 'sv_save_counts',
    args: {
      sv_name: SV.svName,
      counts: JSON.stringify(counts),
      counted_by_1: document.getElementById('sv-counted-by-1').value || '',
      counted_by_2: document.getElementById('sv-counted-by-2').value || '',
      remarks: document.getElementById('sv-setup-remarks').value || '',
      action: 'save'
    },
    freeze: true,
    freeze_message: 'Saving remarks...',
    callback: function(r) {
      SV.items = r.message.items;
      svShowToast('Remarks saved');
    }
  });
}

function svSubmitFinal() {
  // Check all mismatches have remarks
  var missing = 0;
  for (var i = 0; i < SV.items.length; i++) {
    var item = SV.items[i];
    var pt = (item.main_safe || 0) + (item.loose_tray || 0) + (item.outside_display || 0);
    var diff = (item.physical_total || pt) - (item.erp_count || 0);
    if (diff !== 0 && !(item.remark || '').trim()) missing++;
  }
  if (missing > 0) {
    frappe.msgprint(missing + ' difference(s) still need remarks before submitting.');
    return;
  }
  if (!confirm('Submit and lock this verification?')) return;

  var counts = svBuildCountsPayload();
  for (var i = 0; i < SV.items.length; i++) {
    counts[i].rem = SV.items[i].remark || '';
  }
  frappe.call({
    method: 'sv_save_counts',
    args: {
      sv_name: SV.svName,
      counts: JSON.stringify(counts),
      counted_by_1: document.getElementById('sv-counted-by-1').value || '',
      counted_by_2: document.getElementById('sv-counted-by-2').value || '',
      remarks: document.getElementById('sv-setup-remarks').value || '',
      action: 'submit'
    },
    freeze: true,
    freeze_message: 'Submitting...',
    callback: function(r) {
      svGoState('done');
    }
  });
}

function svHandleUpload(inp) {
  var file = inp && inp.files && inp.files[0];
  if (!file) return;

  // If the SV doc isn't created yet, create it first then continue the upload.
  if (!SV.svName) {
    if (!SV.shift) {
      svShowToast('Pick AM or PM first');
      inp.value = '';
      return;
    }
    frappe.call({
      method: 'sv_create_snapshot',
      args: { shift: SV.shift },
      freeze: true, freeze_message: 'Preparing record...',
      callback: function(r) {
        if (r.message && r.message.name) {
          SV.svName = r.message.name;
          SV.items  = r.message.items || SV.items;
          svUploadFile(file, inp);
        } else {
          svShowToast('Could not start record');
          inp.value = '';
        }
      }
    });
    return;
  }
  svUploadFile(file, inp);
}

function svUploadFile(file, inp) {
  var zone = document.getElementById('sv-upload-zone');
  zone.innerHTML = '<p>Uploading...</p><p class="hint">Please wait</p>';

  svResizeImage(file, 1600, 0.85, function(blob) {
    var fd = new FormData();
    var baseName = (file.name || 'sheet').replace(/\.[^.]+$/, '');
    fd.append('file', blob, baseName + '.jpg');
    fd.append('is_private', '1');
    fd.append('doctype', 'Stock Verification');
    fd.append('docname', SV.svName);
    fd.append('fieldname', 'sheet_image');
    fd.append('optimize', '1');

    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/method/upload_file', true);
    var meta = document.querySelector('meta[name="csrf_token"]');
    var csrf = (window.frappe && frappe.csrf_token) || (meta && meta.content) || '';
    if (csrf && csrf !== 'None') xhr.setRequestHeader('X-Frappe-CSRF-Token', csrf);
    xhr.onload = function() {
      try {
        var resp = JSON.parse(xhr.responseText || '{}');
        if (xhr.status >= 200 && xhr.status < 300 && resp.message) {
          SV.uploaded = true;
          zone.classList.add('sv-upload-done');
          zone.innerHTML = '<p>Sheet uploaded</p><p class="hint">Tap to replace</p>';
          svShowToast('Photo attached');
        } else {
          var msg = (resp._server_messages || resp.exc || 'Upload failed').toString().slice(0, 120);
          zone.classList.remove('sv-upload-done');
          zone.innerHTML = '<p>Tap to upload photo</p><p class="hint">Camera or gallery</p>';
          svShowToast('Upload failed: ' + msg);
        }
      } catch (err) {
        zone.innerHTML = '<p>Tap to upload photo</p><p class="hint">Camera or gallery</p>';
        svShowToast('Upload failed (network)');
      }
      inp.value = '';
    };
    xhr.onerror = function() {
      zone.innerHTML = '<p>Tap to upload photo</p><p class="hint">Camera or gallery</p>';
      svShowToast('Upload failed (network)');
      inp.value = '';
    };
    xhr.send(fd);
  });
}

// Resize an image File to max long-edge `maxDim` and return a JPEG Blob.
function svResizeImage(file, maxDim, quality, cb) {
  if (!file.type || file.type.indexOf('image/') !== 0) { cb(file); return; }
  var img = new Image();
  var url = URL.createObjectURL(file);
  img.onload = function() {
    var w = img.width, h = img.height;
    var scale = Math.min(1, maxDim / Math.max(w, h));
    var cw = Math.round(w * scale), ch = Math.round(h * scale);
    var canvas = document.createElement('canvas');
    canvas.width = cw; canvas.height = ch;
    canvas.getContext('2d').drawImage(img, 0, 0, cw, ch);
    canvas.toBlob(function(blob) {
      URL.revokeObjectURL(url);
      cb(blob || file);
    }, 'image/jpeg', quality);
  };
  img.onerror = function() { URL.revokeObjectURL(url); cb(file); };
  img.src = url;
}

function svShowToast(msg) {
  var t = document.createElement('div');
  t.style.cssText = 'position:fixed;bottom:70px;left:50%;transform:translateX(-50%);background:#1a1a1a;color:#f9f8f6;padding:8px 20px;border-radius:20px;font-size:13px;font-weight:600;z-index:200;opacity:0;transition:opacity .2s';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(function(){ t.style.opacity = '1'; }, 10);
  setTimeout(function(){ t.style.opacity = '0'; setTimeout(function(){ t.remove(); }, 200); }, 1800);
}

// Hide default navbar/footer for clean mobile view
document.addEventListener('DOMContentLoaded', function() {
  var navbar = document.querySelector('.navbar');
  var footer = document.querySelector('.web-footer');
  if (navbar) navbar.style.display = 'none';
  if (footer) footer.style.display = 'none';
  svInit();
});

// Fallback if DOMContentLoaded already fired
if (document.readyState !== 'loading') {
  var navbar = document.querySelector('.navbar');
  var footer = document.querySelector('.web-footer');
  if (navbar) navbar.style.display = 'none';
  if (footer) footer.style.display = 'none';
  svInit();
}
