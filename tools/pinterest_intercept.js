// Pinterest network interceptor - captures pin data from API responses
// Inject this into the board page, then scroll to trigger loads

(function() {
  if (window.__PIN_INTERCEPTOR_INSTALLED__) return "already installed";
  window.__PIN_INTERCEPTOR_INSTALLED__ = true;
  window.__CAPTURED_PINS__ = window.__CAPTURED_PINS__ || {};
  window.__CAPTURE_COUNT__ = 0;
  window.__CAPTURE_LOG__ = [];

  function processPinData(pins) {
    if (!Array.isArray(pins)) return;
    pins.forEach(function(p) {
      if (p && p.id && !window.__CAPTURED_PINS__[p.id]) {
        window.__CAPTURED_PINS__[p.id] = p;
        window.__CAPTURE_COUNT__++;
      }
    });
  }

  function processResponse(url, data) {
    try {
      if (data && data.resource_response) {
        var rd = data.resource_response.data;
        if (Array.isArray(rd)) {
          processPinData(rd);
          window.__CAPTURE_LOG__.push({url: url.substring(0, 100), pins: rd.length, total: window.__CAPTURE_COUNT__});
        }
      }
    } catch(e) {
      window.__CAPTURE_LOG__.push({error: e.message});
    }
  }

  // Override fetch
  var origFetch = window.fetch;
  window.fetch = function() {
    var args = arguments;
    var url = typeof args[0] === "string" ? args[0] : (args[0] && args[0].url ? args[0].url : "");
    return origFetch.apply(this, args).then(function(response) {
      if (url.indexOf("/resource/") > -1) {
        response.clone().json().then(function(data) {
          processResponse(url, data);
        }).catch(function(){});
      }
      return response;
    });
  };

  // Override XHR
  var origOpen = XMLHttpRequest.prototype.open;
  var origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, url) {
    this.__captureUrl = url;
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function() {
    var self = this;
    this.addEventListener("load", function() {
      if (self.__captureUrl && self.__captureUrl.indexOf("/resource/") > -1) {
        try {
          processResponse(self.__captureUrl, JSON.parse(self.responseText));
        } catch(e) {}
      }
    });
    return origSend.apply(this, arguments);
  };

  return "Interceptor installed. Scroll to load pins. Check __CAPTURE_COUNT__ for progress.";
})();
