.. _query corrector engine:

======================
Query Corrector Engine
======================

.. automodule:: searx.engines.query_corrector
   :members:

Service contract
================

The engine sends an HTTP ``POST`` request to ``api_path`` below ``base_url``.
The JSON request contains the trimmed query and, when a specific locale is
selected, its SearXNG locale tag::

   {
     "query": "searxng querry",
     "language": "en-US"
   }

The service returns either a conservative correction::

   {"correction": "searxng query"}

or ``null`` when no correction should be offered::

   {"correction": null}

Configuration
=============

The bundled engine is inactive and disabled by default.  Configure an HTTPS
service URL and activate the engine in ``settings.yml``::

   engines:
     - name: query corrector
       base_url: https://corrector.example
       timeout: 1.0
       inactive: false
       disabled: false

Plain HTTP is rejected unless the administrator explicitly adds
``enable_http: true``.  This exception is intended for trusted local services.
The service receives the user's raw search terms, so HTTPS should be used for
remote deployments.

The standard engine ``timeout`` option is applied to the service request and
contributes to the search-wide deadline.  The engine default is ``1.0``
second, which assumes a local service.  Increase it when using a remote
service, where connection establishment and TLS negotiation can take longer.

The engine defaults to ``/v1/correct`` for ``api_path``, ``80`` characters for
``max_query_length``, and ``256`` characters for ``max_correction_length``.
Administrators can override these engine options in ``settings.yml``.

Response filtering
==================

The response is treated as untrusted input.  A correction is ignored unless it
is a non-empty JSON string no longer than ``max_correction_length``.  After
trimming, the engine also rejects corrections that:

* are equivalent to the original query after NFC normalization and
  case-folding;
* contain a whitespace-delimited token beginning with ``!``, ``:``, or ``<``,
  because those prefixes are SearXNG query syntax;
* contain tabs, line breaks, other non-space whitespace, or a character in
  any Unicode ``C*`` general category (control, format, surrogate,
  private-use, or unassigned).

The zero-width non-joiner (U+200C) and zero-width joiner (U+200D) are the only
permitted exceptions to the ``C*`` rule.  Inserting either character can be a
meaningful orthographic correction and is accepted.  A correction that only
deletes such joining characters is ignored as display noise.

A service should return ``{"correction": null}`` whenever it cannot satisfy
these constraints or cannot make a conservative correction.

Service failures
================

The engine does not expose correction-service errors in search results.  A
non-success HTTP response is ignored, while a rate-limited warning is written
to the SearXNG log to make persistent service failures visible to operators.
The warning interval is enforced per worker process; it is not a cluster-wide
or multi-process logging guarantee.
