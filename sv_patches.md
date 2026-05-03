# Stock Verification — Patches

Two surgical edits to the Web Page at `/app/web-page/stock-verification`. No server-script
changes needed.

---

## Patch 1 — "Counted by" autocomplete (all active Employees)

### 1a. Add a `<datalist>` once, just before the `Counted by — Person 1` field
Find this block (around line ~370 in the page HTML):

```html
<div class="sv-card-body">
  <div class="sv-field-group">
    <label class="sv-field-label">Counted by — Person 1</label>
    <input class="sv-field-input" type="text" placeholder="Name" id="sv-counted-by-1">
  </div>
  <div class="sv-field-group">
    <label class="sv-field-label">Counted by — Person 2</label>
    <input class="sv-field-input" type="text" placeholder="Name" id="sv-counted-by-2">
  </div>
```

Replace with:

```html
<div class="sv-card-body">
  <!-- Shared employee suggestions for both Counted By inputs -->
  <datalist id="sv-employee-list"></datalist>

  <div class="sv-field-group">
    <label class="sv-field-label">Counted by — Person 1</label>
    <input class="sv-field-input" type="text" placeholder="Name"
           id="sv-counted-by-1" list="sv-employee-list" autocomplete="off">
  </div>
  <div class="sv-field-group">
    <label class="sv-field-label">Counted by — Person 2</label>
    <input class="sv-field-input" type="text" placeholder="Name"
           id="sv-counted-by-2" list="sv-employee-list" autocomplete="off">
  </div>
```

### 1b. Populate the datalist on init
In `svInit()` (top of the script block), add a call to a new loader function:

```js
function svInit() {
  SV.user = frappe.session.user;
  SV.userFullName = frappe.session.user_fullname || SV.user;
  document.getElementById('sv-user-display').textContent = SV.userFullName;
  document.getElementById('sv-entry-by').value = SV.userFullName;

  // ... existing date display code ...

  svLoadEmployees();   // <-- ADD THIS LINE
  svLoadLanding();
}

function svLoadEmployees() {
  frappe.call({
    method: 'frappe.client.get_list',
    args: {
      doctype: 'Employee',
      filters: { status: 'Active' },
      fields: ['employee_name'],
      limit_page_length: 0,    // no cap — return all
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
```

**Also fix** the "Data entry by" field showing `undefined`. In `svInit()`, change:

```js
document.getElementById('sv-entry-by').value = SV.userFullName;
```

to:

```js
document.getElementById('sv-entry-by').value = SV.userFullName || SV.user || '';
```

`frappe.session.user_fullname` is sometimes `undefined` on a fresh Web Page session — falling
back to email avoids the `undefined` you screenshotted.

---

## Patch 2 — Photo upload rewrite

Replace the entire `svHandleUpload` function with the version below. It:

1. Creates the SV doc first if `SV.svName` is empty (so users can upload immediately).
2. Resizes the image client-side to max 1600 px JPEG @ 0.85 — keeps mobile uploads small.
3. Uses `multipart/form-data` POST to `/api/method/upload_file` with the CSRF token —
   the form that actually works on Web Pages, not the JSON `frappe.call`.
4. Marks the file `is_private: 1`.
5. Shows toasts on success and on error, with the server message.
6. Allows re-upload to replace.

```js
function svHandleUpload(inp) {
  var file = inp && inp.files && inp.files[0];
  if (!file) return;

  // If the SV doc isn't created yet, create it first then retry the upload.
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
    fd.append('file', blob, (file.name || 'sheet').replace(/\.[^.]+$/, '') + '.jpg');
    fd.append('is_private', '1');
    fd.append('doctype', 'Stock Verification');
    fd.append('docname', SV.svName);
    fd.append('fieldname', 'sheet_image');
    fd.append('optimize', '1');

    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/method/upload_file', true);
    var csrf = (window.frappe && frappe.csrf_token) ||
               document.querySelector('meta[name="csrf_token"]') &&
               document.querySelector('meta[name="csrf_token"]').content;
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
      inp.value = '';   // allow re-selecting the same file later
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
  // Non-images: send as-is.
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
```

### Required: server permission

For the Web Page user role (whichever role your counters log in as), make sure
`Stock Verification` has **write** permission and **attach** permission. Without it,
`/api/method/upload_file` returns 403 and the toast will say `Upload failed: ...permitted...`.

If you also want to allow uploading the photo *before* picking AM/PM (e.g. from the
landing screen), the auto-create branch above won't trigger because `SV.shift` is empty —
keep upload restricted to state `0b` like it already is and you're fine.

---

## After applying

1. Save the Web Page (clears server-side render cache automatically).
2. Hard refresh the mobile browser (clear cache / Cmd-Shift-R) so the new JS loads.
3. Test:
   - Tap "Counted by — Person 1" → typing should show employee suggestions.
   - Tap upload → pick a photo → expect "Photo attached" toast and a "Sheet uploaded · Tap to replace" zone.
   - Open the SV record in desk and confirm `sheet_image` has a file attached and `is_private = 1`.

Report any error toast text back and I'll adjust — common ones are *PermissionError* (role
missing attach perms) or *RequestEntityTooLarge* (nginx `client_max_body_size`, raise to
20 MB).
